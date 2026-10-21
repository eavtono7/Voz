"""
Main GUI application for Voz voice dictation.

The App class *coordinates* specialised modules (Recorder, Transcriber,
Clipboard, Storage) without doing any of the heavy work itself.

States
------
    idle        – waiting for F10
    recording   – microphone is capturing audio
    transcribing – faster-whisper is processing
    copying     – pushing text to the clipboard
    storing     – writing .txt / .json to disk
    done        – cycle complete, back to idle after 2 s
    error       – something went wrong
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

from core import config
from core.recorder import Recorder, RecorderError
from core.transcriber import Transcriber, TranscriberError
from core.clipboard import Clipboard
from core.storage import Storage
from gui.hotkey_listener import HotkeyListener, HotkeyListenerError
from gui.settings_window import SettingsWindow

logger = logging.getLogger(__name__)


class App(tk.Tk):
    """Main dictation window."""

    # ── State definitions ────────────────────────────────────────────────
    STATUS_TEXT: dict[str, str] = {
        "idle":         "🟢  Listo — presiona {} para grabar",
        "recording":    "🔴  Grabando... {0:.1f}s — {1} para detener",
        "transcribing": "🟡  Transcribiendo audio...",
        "copying":      "📋  Copiando al portapapeles...",
        "storing":      "💾  Guardando...",
        "done":         "✅  Listo — {0:.1f}s de audio · {1} caracteres · {2:.1f}s de proceso",
        "error":        "❌  {}",
    }

    STATUS_COLOR: dict[str, str] = {
        "idle":         "#4ec9b0",
        "recording":    "#f44747",
        "transcribing": "#dcdcaa",
        "copying":      "#569cd6",
        "storing":      "#569cd6",
        "done":         "#4ec9b0",
        "error":        "#f44747",
    }

    def __init__(self) -> None:
        super().__init__()

        self.title("Voz — Dictado por voz")
        self.geometry("900x880")
        self.minsize(800, 800)

        # ── State ────────────────────────────────────────────────────────
        self._state: str = "idle"
        self._session_count: int = 0

        # ── Feedback timers / done-context ──────────────────────────────
        self._recording_tick_id: str | None = None
        self._flash_restore_id: str | None = None
        self._last_audio_secs: float = 0.0
        self._last_chars: int = 0
        self._last_proc_secs: float = 0.0

        # ── Core modules (no file I/O, no mic access on init) ────────────
        self._recorder = Recorder(device=config.MICROPHONE_DEVICE)
        self._transcriber = Transcriber()
        self._clipboard = Clipboard()
        self._storage = Storage(config.DICTATIONS_DIR)

        # ── Threading ────────────────────────────────────────────────────
        self._transcription_thread: threading.Thread | None = None

        # ── Thread-safe event plumbing ───────────────────────────────────
        # pynput's listener thread must never call tkinter directly. It only
        # posts to this queue; a poller on the Tk thread consumes it.
        self._events: queue.Queue[str] = queue.Queue()
        self._running: bool = True

        # ── Transcript store (only real dictation text, no status logs) ──
        self._transcripts: list[str] = []

        # ── Timers / deferred work ───────────────────────────────────────
        self._return_to_idle_id: str | None = None
        self._pending_settings: bool = False
        self._pending_hotkey: bool = False  # hotkey pressed mid-transcription
        self._unload_timer_id: str | None = None
        self._model_asleep: bool = False  # model freed from RAM by idle TTL

        # ── Build UI ─────────────────────────────────────────────────────
        logger.debug("Building UI...")
        self._build_ui()
        logger.debug("Applying theme...")
        self._apply_theme()
        logger.debug("Setting up event poller...")
        self._start_event_poller()
        self.update()  # Force initial render
        logger.debug("UI built successfully")

        # ── Services ─────────────────────────────────────────────────────
        logger.debug("Setting up hotkey...")
        self._setup_hotkey()
        logger.debug("All services initialized")

        # ── Window close ─────────────────────────────────────────────────
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════════
    # UI
    # ═══════════════════════════════════════════════════════════════════════

    def _apply_theme(self) -> None:
        """Global dark-theme styles."""
        self.configure(bg="#1e1e1e")
        self.tk.call("ttk::style", "theme", "use", "clam")

    def _build_ui(self) -> None:
        """Create all widgets."""
        # ── Main container ───────────────────────────────────────────────
        main = tk.Frame(self, bg="#1e1e1e")
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # ── Header banner ────────────────────────────────────────────────
        banner_frame = tk.Frame(main, bg="#1e1e1e")
        banner_frame.pack(fill="x", pady=(0, 2))

        tk.Label(
            banner_frame,
            text=(
                "\u25A0  V O Z    D i c t a d o   p o r   v o z"
            ),
            bg="#1e1e1e",
            fg="#4ec9b0",
            font=("Consolas", 14, "bold"),
        ).pack()

        sep = tk.Frame(main, bg="#3a3a3a", height=1)
        sep.pack(fill="x")

        # ── Progress bar (hidden by default) ───────────────────────────
        self._progress_frame = tk.Frame(main, bg="#1e1e1e")
        self._progress_lbl = tk.Label(
            self._progress_frame,
            text="",
            bg="#1e1e1e",
            fg="#dcdcaa",
            font=("Segoe UI", 9),
        )
        self._progress_bar = tk.Frame(
            self._progress_frame,
            bg="#2d2d2d",
            height=3,
        )
        self._progress_fill = tk.Frame(
            self._progress_bar,
            bg="#4ec9b0",
            width=0,
        )
        self._progress_fill.place(relheight=1, relwidth=0)

        # ── Text area ────────────────────────────────────────────────────
        txt_container = tk.Frame(main, bg="#2d2d2d")
        txt_container.pack(fill="both", expand=True)

        self._text = tk.Text(
            txt_container,
            bg="#1a1a1a", fg="#e0e0e0",
            insertbackground="#4ec9b0",
            font=("Segoe UI", 11),
            wrap="word",
            relief="flat",
            padx=12, pady=12,
            spacing1=4, spacing3=4,
        )
        self._text.pack(side="left", fill="both", expand=True)

        scroll = tk.Scrollbar(
            txt_container, command=self._text.yview,
            bg="#2d2d2d", troughcolor="#1a1a1a",
        )
        scroll.pack(side="right", fill="y")
        self._text.configure(yscrollcommand=scroll.set)

        # Tags for styling inserted text
        self._text.tag_configure(
            "timestamp", foreground="#6a9955", font=("Segoe UI", 8),
        )
        self._text.tag_configure("text", foreground="#e0e0e0")

        # ── Status bar ───────────────────────────────────────────────────
        status_frame = tk.Frame(main, bg="#2d2d2d", height=38)
        status_frame.pack(fill="x", pady=(8, 0))
        status_frame.pack_propagate(False)

        self._status_lbl = tk.Label(
            status_frame,
            text=self.STATUS_TEXT["idle"].format(config.HOTKEY),
            bg="#2d2d2d", fg=self.STATUS_COLOR["idle"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self._status_lbl.pack(side="left", padx=12)

        self._counter_lbl = tk.Label(
            status_frame,
            text="", bg="#2d2d2d", fg="#808080",
            font=("Segoe UI", 9),
            anchor="e",
        )
        self._counter_lbl.pack(side="right", padx=12)

        # ── Button bar ──────────────────────────────────────────────────
        btn_bar = tk.Frame(main, bg="#1e1e1e")
        btn_bar.pack(fill="x", pady=(8, 0))

        buttons = [
            ("📋  Copiar",       self._copy_text,      True),
            ("🗑️  Limpiar",      self._clear_text,     False),
            ("💾  Guardar como...", self._save_as,      True),
            ("⚙️  Configurar",   self._open_settings,  False),
        ]
        for text, cmd, _ in buttons:
            tk.Button(
                btn_bar, text=text, command=cmd,
                bg="#3a3a3a", fg="#e0e0e0",
                relief="flat", padx=14, pady=4, cursor="hand2",
                font=("Segoe UI", 9),
                activebackground="#4a4a4a", activeforeground="#ffffff",
            ).pack(side="left", padx=(0, 8))

        # ── Footer hint ──────────────────────────────────────────────────
        tk.Label(
            main,
            text="Presiona {} para grabar • Presiona otra vez para detener".format(
                config.HOTKEY,
            ),
            bg="#1e1e1e", fg="#555555",
            font=("Segoe UI", 8),
        ).pack(pady=(6, 0))

    # ═══════════════════════════════════════════════════════════════════════
    # Hotkey & tray
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_hotkey(self) -> None:
        """Start the global hotkey listener."""
        try:
            self._hotkey = HotkeyListener(callback=self._on_hotkey)
            self._hotkey.start(config.HOTKEY)
        except HotkeyListenerError as exc:
            logger.error("Hotkey not available: %s", exc)
            messagebox.showwarning(
                "Tecla rápida no disponible",
                f"No se pudo registrar la tecla {config.HOTKEY}.\n\n"
                "Prueba ejecutando como Administrador o elige otra tecla en Configuración.",
            )

    # ── Thread-safe event plumbing ────────────────────────────────────────

    _EVENT_HOTKEY = "hotkey"

    def _start_event_poller(self) -> None:
        """Drain cross-thread events on the Tk thread (every 50 ms)."""
        self.after(50, self._poll_events)

    def _poll_events(self) -> None:
        if not self._running:
            return
        try:
            while True:
                event = self._events.get_nowait()
                if event == self._EVENT_HOTKEY:
                    self._handle_hotkey()
                else:
                    logger.warning("Unknown event in queue: %r", event)
        except queue.Empty:
            pass
        self.after(50, self._poll_events)

    def _on_hotkey(self) -> None:
        """Called by pynput on a background thread – post to queue (thread-safe)."""
        self._events.put(self._EVENT_HOTKEY)

    def _handle_hotkey(self) -> None:
        """React to hotkey based on current state."""
        logger.info("_handle_hotkey called, current state: %s", self._state)
        if self._state == "idle":
            self._start_recording()
        elif self._state == "recording":
            self._stop_and_transcribe()
        elif self._state == "transcribing":
            # Buffer the press instead of dropping it: the new dictation
            # starts as soon as the current cycle returns to idle.
            self._pending_hotkey = True
            self._flash("⏳  En cola — iniciará al terminar la actual")
        elif self._state == "done":
            # A press during the brief "done" window must not be lost:
            # cancel the pending idle transition and record immediately.
            if self._return_to_idle_id is not None:
                try:
                    self.after_cancel(self._return_to_idle_id)
                except Exception:
                    pass
                self._return_to_idle_id = None
            self._start_recording()
        elif self._state == "error":
            # Next press after an error starts a fresh dictation attempt.
            self._log_status("🔄  Reintentando...")
            self._start_recording()

    # ═══════════════════════════════════════════════════════════════════════
    # State machine
    # ═══════════════════════════════════════════════════════════════════════

    def _set_state(self, state: str, detail: str = "") -> None:
        """Update the internal state and the status label."""
        logger.debug("_set_state: %s → %s (detail: %s)", self._state, state, detail)
        self._state = state

        template = self.STATUS_TEXT.get(state, self.STATUS_TEXT["idle"])
        hotkey = config.HOTKEY

        if state == "idle":
            text = template.format(hotkey)
            if self._model_asleep and not self._transcriber.is_model_loaded:
                text += "  ·  💤 modelo en reposo (recarga ~3 s)"
        elif state == "recording":
            # Live counter fed by _tick_recording between _set_state calls
            text = template.format(self._recorder.recording_duration, hotkey)
        elif state == "done":
            text = template.format(
                self._last_audio_secs, self._last_chars, self._last_proc_secs
            )
        elif state == "error":
            text = template.format(detail or "Error desconocido")
        else:
            text = template

        self._status_lbl.configure(
            text=text,
            fg=self.STATUS_COLOR.get(state, "#e0e0e0"),
        )
        self._force_paint()

    # ── Friendly errors ───────────────────────────────────────────────────

    _ERROR_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
        (
            (
                "microphone",
                "input device",
                "no default input",
                "unable to open",
                "invalid input device",
                "device not found",
                "format not supported",
            ),
            "Micrófono no disponible — revisa Configuración",
        ),
        (("busy", "in use", "already in use"), "Micrófono en uso por otra aplicación"),
        (("empty audio", "cannot transcribe empty"), "No se capturó audio"),
        (("language code", "not a valid language"), "Idioma inválido — revisa Configuración"),
        (
            ("download", "connection", "huggingface", "network", "timeout"),
            "Error de red al descargar el modelo",
        ),
    )

    @staticmethod
    def _friendly_error(detail: str) -> str:
        """Map raw exception text to a short Spanish user-facing message.

        The raw detail is always preserved in the widget log and voz.log;
        this only shapes what the status bar shows.
        """
        low = (detail or "").lower()
        for patterns, friendly in App._ERROR_PATTERNS:
            if any(p in low for p in patterns):
                return friendly
        return (detail or "Error desconocido")[:120]

    # ── Recording tick (live seconds counter) ────────────────────────────

    _REC_TICK_MS = 500

    def _start_recording_tick(self) -> None:
        """Schedule the live recording counter (cancels any previous one)."""
        self._cancel_recording_tick()
        self._recording_tick_id = self.after(self._REC_TICK_MS, self._tick_recording)

    def _cancel_recording_tick(self) -> None:
        if self._recording_tick_id is not None:
            try:
                self.after_cancel(self._recording_tick_id)
            except Exception:
                pass
            self._recording_tick_id = None

    def _tick_recording(self) -> None:
        """Refresh the status bar with the seconds actually captured."""
        if self._state != "recording" or not self._running:
            self._recording_tick_id = None
            return
        self._status_lbl.configure(
            text=self.STATUS_TEXT["recording"].format(
                self._recorder.recording_duration, config.HOTKEY
            ),
            fg=self.STATUS_COLOR["recording"],
        )
        self._force_paint()
        self._recording_tick_id = self.after(self._REC_TICK_MS, self._tick_recording)

    # ── Transitions ───────────────────────────────────────────────────────

    def _start_recording(self) -> None:
        """IDLE → RECORDING"""
        logger.info("_start_recording called")
        self._cancel_model_unload()  # user is active again
        try:
            logger.debug("Calling recorder.start()")
            self._recorder.start()
            logger.info("Recorder started successfully")
            self._set_state("recording")
            self._start_recording_tick()
            self._log_status("🎙️  Grabación iniciada — habla ahora")
        except RecorderError as exc:
            logger.error("RecorderError: %s", exc, exc_info=True)
            self._set_state("error", self._friendly_error(str(exc)))
            self._log_status(f"❌  Error: {exc}")
        except Exception as exc:
            logger.error("Unexpected error in _start_recording: %s", exc, exc_info=True)
            self._set_state("error", self._friendly_error(str(exc)))
            self._log_status(f"❌  Error inesperado: {exc}")

    def _stop_and_transcribe(self) -> None:
        """RECORDING → TRANSCRIBING (stop + resample + transcribe off-thread).

        recorder.stop() may take hundreds of ms on long dictations (buffer
        concat + resample) — never run it on the UI thread.
        """
        logger.info("_stop_and_transcribe called")
        self._cancel_recording_tick()  # stop the live counter
        self._set_state("transcribing")
        self._log_status("🔄  Transcribiendo...")

        logger.debug("Starting transcription worker thread")
        self._transcription_thread = threading.Thread(
            target=self._worker_transcribe,
            daemon=True,
        )
        self._transcription_thread.start()
        logger.info("Transcription thread started")

    def _worker_transcribe(self) -> None:
        """Stop the recorder and run faster-whisper — all on a background thread."""
        try:
            audio = self._recorder.stop()
        except RecorderError as exc:
            logger.error("RecorderError in worker: %s", exc, exc_info=True)
            self._safe_after(self._on_transcription_error, f"Error al detener la grabación: {exc}")
            return
        except Exception as exc:
            logger.exception("Unexpected error stopping the recorder in worker")
            self._safe_after(self._on_transcription_error, f"Error al detener la grabación: {exc}")
            return

        if len(audio) == 0:
            logger.warning("Audio is empty, returning to idle")
            self._safe_after(self._on_empty_audio)
            return

        if not self._transcriber.is_model_loaded:
            msg = (
                "Esperando descarga del modelo..."
                if not self._transcriber.is_model_cached()
                else "Cargando modelo en RAM..."
            )
            self._safe_after(self._flash_status, msg, "#dcdcaa")

        audio_secs = len(audio) / config.SAMPLE_RATE
        self._safe_after(self._show_transcribing_duration, audio_secs)

        try:
            logger.info("Worker transcribing %d samples", len(audio))
            t0 = time.monotonic()
            result = self._transcriber.transcribe(audio)
            proc_secs = time.monotonic() - t0
            logger.info(
                "Transcription completed, text length: %d, proc %.2fs",
                len(result.text),
                proc_secs,
            )
            self._safe_after(self._on_transcription_done, result, proc_secs)
        except TranscriberError as exc:
            logger.exception("Transcription failed")
            self._safe_after(self._on_transcription_error, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error in _worker_transcribe")
            self._safe_after(self._on_transcription_error, str(exc))

    def _worker_save(self, result, filename) -> None:
        """Save transcription result in a background thread."""
        storage = self._storage  # capture: settings can swap it mid-save
        try:
            storage.save(result, filename)
        except Exception as exc:
            logger.error("Auto-save failed: %s", exc)
            self._safe_after(self._flash, f"⚠️  Auto-guardado falló: {exc}")

    def _on_transcription_done(self, result, proc_secs: float = 0.0) -> None:
        """TRANSCRIBING → COPYING → STORING → DONE"""
        logger.info("_on_transcription_done called, text: %s", result.text[:50] if result.text else "(empty)")
        self._model_asleep = False  # transcribing reloads the model if needed
        self._session_count += 1
        dur = result.duration
        self._last_audio_secs = dur
        self._last_chars = len(result.text)
        self._last_proc_secs = proc_secs

        # ── Copy ─────────────────────────────────────────────────────
        if config.AUTO_COPY:
            logger.debug("Auto-copy enabled, copying to clipboard")
            self._set_state("copying")
            if not self._clipboard.copy(result.text):
                logger.warning("Auto-copy failed – clipboard unavailable")
                self._log_status("⚠️  No se pudo copiar al portapapeles")
            else:
                self._log_status("📋  Copiado al portapapeles")

        # ── Store (background thread – don't block the GUI) ──────────
        if config.AUTO_SAVE:
            logger.debug("Auto-save enabled, starting save thread")
            self._set_state("storing")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            threading.Thread(
                target=self._worker_save,
                args=(result, f"dictado_{timestamp}"),
                daemon=True,
            ).start()

        # ── Display ──────────────────────────────────────────────────
        logger.debug("Appending text to UI")
        self._append_text(result)

        # ── Done → idle after 2 s ────────────────────────────────────
        logger.info("Setting state to done, will return to idle in 2s")
        self._set_state("done")
        self._log_status(
            f"✅  Transcripción completada "
            f"({dur:.1f}s audio · {len(result.text)} chars · {proc_secs:.1f}s proceso)"
        )
        self._return_to_idle_id = self.after(2_000, self._return_to_idle)

    def _on_transcription_error(self, msg: str) -> None:
        """TRANSCRIBING → ERROR (friendly in the bar, raw in the widget log)."""
        logger.error("_on_transcription_error called: %s", msg)
        self._set_state("error", self._friendly_error(msg))
        self._log_status(f"❌  Error de transcripción: {msg}")

    def _on_empty_audio(self) -> None:
        """TRANSCRIBING → IDLE (worker produced no samples)."""
        self._cancel_recording_tick()
        self._set_state("idle")
        self._log_status("⚠️  No se capturó audio")
        if self._pending_settings:
            self._pending_settings = False
            self._on_settings_saved()
        if self._pending_hotkey:
            self._pending_hotkey = False
            self._start_recording()
            return
        self._schedule_model_unload()

    def _show_transcribing_duration(self, audio_secs: float) -> None:
        """Show how much recorded audio is being processed (Tk thread only)."""
        if self._state != "transcribing":
            return
        self._status_lbl.configure(
            text=f"🟡  Transcribiendo {audio_secs:.1f}s de audio...",
            fg=self.STATUS_COLOR["transcribing"],
        )
        self._force_paint()
        self._log_status(f"⏳  {audio_secs:.1f}s de audio en transcripción")

    def _return_to_idle(self) -> None:
        """DONE → IDLE"""
        self._return_to_idle_id = None
        self._set_state("idle")
        if self._pending_settings:
            self._pending_settings = False
            self._on_settings_saved()
        if self._pending_hotkey:
            self._pending_hotkey = False
            self._start_recording()
            return
        self._schedule_model_unload()

    def _log_status(self, msg: str) -> None:
        """Write a status message to the text area."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.insert("end", f"\n[{ts}] {msg}\n", "timestamp")
        self._text.see("end")
        self._force_paint()

    # ── Text area helpers ───────────────────────────────────────────────

    def _append_text(self, result) -> None:
        """Insert a new transcription block into the text widget."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.insert("end", f"\n[{ts}]  ({result.duration:.1f}s  {result.language})\n", "timestamp")
        self._text.insert("end", f"{result.text}\n", "text")
        self._text.see("end")

        if result.text.strip():
            self._transcripts.append(result.text)

        self._counter_lbl.configure(
            text=f"Dictados hoy: {self._session_count}  ·  Último: {result.duration:.1f}s",
        )

    def _current_transcripts(self) -> str:
        """Only real dictation text — never the [hh:mm:ss] status log."""
        return "\n".join(t for t in self._transcripts if t.strip())

    # ═══════════════════════════════════════════════════════════════════════
    # Button actions
    # ═══════════════════════════════════════════════════════════════════════

    def _copy_text(self) -> None:
        text = self._current_transcripts()
        if not text:
            return
        if self._clipboard.copy(text):
            self._flash("📋  ¡Copiado!")
        else:
            self._flash("❌  No se pudo copiar")

    def _clear_text(self) -> None:
        if not self._current_transcripts() and not self._text.get("1.0", "end-1c").strip():
            return
        if messagebox.askyesno("Limpiar", "¿Borrar todo el texto acumulado?"):
            self._text.delete("1.0", "end")
            self._transcripts.clear()
            self._counter_lbl.configure(text="")
            self._flash("🗑️  Texto borrado")

    def _save_as(self) -> None:
        text = self._current_transcripts()
        if not text:
            messagebox.showinfo("Guardar", "No hay texto para guardar")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Archivos de texto", "*.txt"), ("Todos", "*.*")],
            initialdir=str(config.DICTATIONS_DIR),
        )
        if not path:
            return

        try:
            Path(path).write_text(text, encoding="utf-8")
            self._flash(f"💾  Guardado en: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo guardar:\n{exc}")

    def _open_settings(self) -> None:
        SettingsWindow(self, on_save=self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        """Recreate modules that depend on changed config values.

        Deferred while a dictation cycle is running: swapping Recorder or
        Transcriber mid-cycle would orphan an open mic stream or an in-flight
        model. The pending changes are applied when the cycle returns to idle.
        """
        if self._state in ("recording", "transcribing"):
            self._pending_settings = True
            self._log_status("⚙️  Cambios guardados — se aplicarán al terminar el dictado")
            return

        if self._recorder.device != config.MICROPHONE_DEVICE:
            self._recorder = Recorder(device=config.MICROPHONE_DEVICE)
        if self._transcriber.model_name != config.MODEL:
            self._transcriber.unload()
            self._transcriber = Transcriber()
        self._storage = Storage(config.DICTATIONS_DIR)
        try:
            self._hotkey.restart(config.HOTKEY)
        except HotkeyListenerError as exc:
            logger.error("Failed to restart hotkey: %s", exc)
            messagebox.showwarning(
                "Tecla rápida no disponible",
                f"No se pudo registrar la tecla {config.HOTKEY}.\n\n"
                f"{exc}\n\nElige otra tecla en Configuración.",
            )
        self._flash("⚙️  Configuración actualizada")

    def _flash_status(self, msg: str, color: str | None = None) -> None:
        """Update status bar and log the message atomically (prevents UI freeze)."""
        color = color or self.STATUS_COLOR.get(self._state, "#e0e0e0")
        self._status_lbl.configure(text=msg, fg=color)
        self._log_status(msg)

    def _safe_after(self, func, *args, delay_ms: int = 0) -> None:
        """Schedule func(*args) on the Tk thread from any thread (safe on close).

        background threads (worker, pynput, preloader) may still be alive when
        the window is destroyed; plain after() would raise TclError inside them.
        """
        try:
            self.after(delay_ms, func, *args)
        except tk.TclError:
            logger.debug("after(%d) failed – app shutting down", delay_ms)

    def _force_paint(self) -> None:
        """Force immediate window repaint via Win32 API (works without focus)."""
        self.update_idletasks()
        try:
            ctypes.windll.user32.UpdateWindow(self.winfo_id())
        except Exception:
            pass

    def _flash(self, msg: str, duration_ms: int = 2_500) -> None:
        """Show a temporary message in the status bar (2.5 s by default).

        Only one restore timer is ever pending: a new flash cancels the
        previous restore, otherwise stacked restores repaint stale states.
        """
        self._status_lbl.configure(text=msg, fg="#4ec9b0")
        self._force_paint()
        if self._flash_restore_id is not None:
            try:
                self.after_cancel(self._flash_restore_id)
            except Exception:
                pass
        self._flash_restore_id = self.after(
            duration_ms, lambda: self._set_state(self._state)
        )

    # ── Idle model unload (frees ~1.5 GB of RAM) ─────────────────────────

    def _schedule_model_unload(self) -> None:
        """Arm the idle-unload timer after a finished cycle (or pre-load)."""
        self._cancel_model_unload()
        minutes = config.MODEL_UNLOAD_MIN
        if minutes <= 0 or not self._transcriber.is_model_loaded:
            return
        self._unload_timer_id = self.after(
            minutes * 60_000, self._unload_model_now
        )

    def _cancel_model_unload(self) -> None:
        if self._unload_timer_id is not None:
            try:
                self.after_cancel(self._unload_timer_id)
            except Exception:
                pass
            self._unload_timer_id = None

    def _mark_model_awake(self) -> None:
        """Model is loaded in RAM again (idle status suffix disappears)."""
        self._model_asleep = False
        self._set_state(self._state)

    def _unload_model_now(self) -> None:
        """Free the model from RAM after N idle minutes (config.MODEL_UNLOAD_MIN)."""
        self._unload_timer_id = None
        if self._state != "idle" or not self._transcriber.is_model_loaded:
            return
        busy = (
            self._transcription_thread is not None
            and self._transcription_thread.is_alive()
        )
        if busy:
            logger.info("Unload timer fired during transcription – rearming")
            self._schedule_model_unload()
            return
        self._transcriber.unload()
        self._model_asleep = True
        logger.info(
            "Model unloaded after %d idle minute(s) (~1.5 GB RAM freed)",
            config.MODEL_UNLOAD_MIN,
        )
        self._log_status(
            "🛌  Modelo en reposo — se recarga automáticamente al dictar (~3 s)"
        )
        self._flash(
            "🛌  Modelo en reposo — se recarga al dictar (~3 s)",
            duration_ms=5_000,
        )

    def _on_close(self) -> None:
        """Close button → stop recording if active and exit."""
        self._running = False
        self._pending_hotkey = False
        self._cancel_recording_tick()
        self._cancel_model_unload()
        if self._flash_restore_id is not None:
            try:
                self.after_cancel(self._flash_restore_id)
            except Exception:
                pass
            self._flash_restore_id = None

        if self._state == "recording":
            # Teardown off the UI thread: stop() may take a while on long
            # dictations (buffer concat + resample). Daemon thread dies with
            # the process if it does not finish in time.
            def _drain_recorder() -> None:
                try:
                    self._recorder.stop()
                except Exception:
                    logger.debug("Recorder stop during close failed", exc_info=True)

            threading.Thread(target=_drain_recorder, daemon=True).start()

        # Never block the close on a long transcription: the thread is a
        # daemon and its after() callbacks tolerate a destroyed window.
        if (
            self._transcription_thread is not None
            and self._transcription_thread.is_alive()
        ):
            self._transcription_thread.join(timeout=1)

        if hasattr(self, "_hotkey"):
            self._hotkey.stop()

        self.destroy()

    def run(self) -> None:
        """Start the tkinter event loop."""
        logger.info("Forcing window to front...")
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))
        logger.info("Window state: %s", self.state())
        logger.info("Window geometry: %s", self.geometry())

        self._preload_model()

        try:
            self.mainloop()
        except KeyboardInterrupt:
            self._on_close()
        finally:
            logger.info("Application shut down")

    def _preload_model(self) -> None:
        """Start background model loading with progress feedback."""
        if self._transcriber.is_model_loaded:
            return

        cached = self._transcriber.is_model_cached()
        if cached:
            self._show_progress("Cargando modelo en RAM...")
        else:
            self._show_progress("Descargando modelo (~1.5 GB)...")

        # Capture the instance this preload belongs to: swapping Transcriber
        # via settings mid-load must not confuse the completion callbacks.
        transcriber = self._transcriber

        def _load() -> None:
            try:
                transcriber.preload()
            except Exception as exc:
                logger.warning("Model preload failed (will retry on dictation): %s", exc)
                self._safe_after(self._hide_progress)
                return
            if transcriber is not self._transcriber:
                logger.debug("Preload finished after a Transcriber swap – feedback skipped")
                self._safe_after(self._hide_progress)
                return
            self._safe_after(self._hide_progress)
            self._safe_after(self._flash_status, "Modelo listo", "#4ec9b0")
            self._safe_after(self._mark_model_awake)
            self._safe_after(self._set_state, self._state, delay_ms=2_000)
            self._safe_after(self._schedule_model_unload)

        threading.Thread(target=_load, daemon=True).start()

    def _show_progress(self, msg: str) -> None:
        """Display an indeterminate progress bar with a label."""
        self._progress_lbl.configure(text=msg)
        self._progress_fill.place(relwidth=0)
        self._progress_frame.pack(
            fill="x", pady=(2, 4), before=self._text.master
        )
        self._progress_bar.pack(fill="x", pady=(2, 0))

        self._log_status(msg)

        self._anim_running = True

        def _animate(step: int = 0) -> None:
            if not getattr(self, "_anim_running", False):
                return
            w = (step % 100) / 100.0
            self._progress_fill.place(relwidth=0.15 + w * 0.4)
            self._progress_id = self.after(80, _animate, step + 1)

        _animate(0)
        self._force_paint()

    def _hide_progress(self) -> None:
        """Remove the progress bar."""
        self._anim_running = False
        if hasattr(self, "_progress_id"):
            self.after_cancel(self._progress_id)
        self._progress_frame.pack_forget()
        self._progress_bar.pack_forget()


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Launch the GUI application.

    On first launch (no config.json), opens the Settings window
    automatically so the user can configure mic and language.
    """
    logger.info("Starting GUI main()")
    app = App()

    if not config.CONFIG_PATH.exists():
        logger.info("First launch – opening Settings automatically")
        app.after(150, lambda: SettingsWindow(
            app, on_save=lambda: _on_first_config(app),
        ))

    app.run()


def _on_first_config(app: App) -> None:
    """Reload config and apply saved values after first-run setup."""
    config.init()
    app._on_settings_saved()
