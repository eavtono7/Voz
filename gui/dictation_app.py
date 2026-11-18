"""
Main GUI application for Voz voice dictation.

The App class *coordinates* specialised modules (Recorder, Transcriber,
Clipboard, Storage) without doing any of the heavy work itself.

States
------
    idle         – waiting for the hotkey
    recording    – microphone is capturing audio
    transcribing – faster-whisper is processing (hotkey is ignored)
    done         – text copied / pasted, back to idle after 2 s
    error        – something went wrong; the next hotkey press retries

Threads
-------
Only the Tk thread touches widgets or the state machine. Background threads
(pynput listener, transcription worker, model loader) hand their results
over with ``_post()``, which the Tk thread drains every few milliseconds.
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

from core import config, sounds
from core.recorder import Recorder
from core.transcriber import Transcriber
from core.clipboard import Clipboard
from core.storage import Storage
from gui.hotkey_listener import HotkeyListener, HotkeyListenerError
from gui.settings_window import SettingsWindow

logger = logging.getLogger(__name__)


class App(tk.Tk):
    """Main dictation window."""

    STATUS_COLOR: dict[str, str] = {
        "idle":         "#4ec9b0",
        "recording":    "#f44747",
        "transcribing": "#dcdcaa",
        "done":         "#4ec9b0",
        "error":        "#f44747",
    }

    _POLL_MS = 25          # how often the Tk thread drains _post()ed work
    _REC_TICK_MS = 500     # live "Grabando... 12.5s" refresh
    _DONE_MS = 2_000       # how long the "done" summary stays before idle

    def __init__(self) -> None:
        super().__init__()

        self.title("Voz — Dictado por voz")
        self.geometry("640x440")

        # ── State ────────────────────────────────────────────────────────
        self._state: str = "idle"
        self._state_detail: str = ""          # error text / done outcome
        self._transcribing_note: str = ""     # what the worker is doing now
        self._session_count: int = 0
        self._last_audio_secs: float = 0.0
        self._last_chars: int = 0
        self._last_proc_secs: float = 0.0
        self._model_asleep: bool = False      # model freed from RAM by idle TTL
        self._pending_settings: bool = False  # settings saved mid-dictation
        self._running: bool = True

        # ── Timers ───────────────────────────────────────────────────────
        self._recording_tick_id: str | None = None
        self._flash_restore_id: str | None = None
        self._return_to_idle_id: str | None = None
        self._unload_timer_id: str | None = None
        self._progress_id: str | None = None

        # ── Core modules (no file I/O, no mic access on init) ────────────
        self._recorder = Recorder(device=config.MICROPHONE_DEVICE)
        self._transcriber = Transcriber()
        self._clipboard = Clipboard()
        self._storage = Storage(config.DICTATIONS_DIR)
        self._transcription_thread: threading.Thread | None = None

        # ── Cross-thread hand-over (see module docstring) ────────────────
        self._events: queue.Queue = queue.Queue()

        self._build_ui()
        self.after(self._POLL_MS, self._poll_events)
        self.update()  # Force initial render

        self._setup_hotkey()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════════
    # UI
    # ═══════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """Create all widgets.

        The button and status bars are packed first (from the bottom) so
        they stay visible however small the window gets; the text area
        takes whatever space is left.
        """
        self.configure(bg="#1e1e1e")
        self.tk.call("ttk::style", "theme", "use", "clam")

        main = tk.Frame(self, bg="#1e1e1e")
        main.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Button bar ───────────────────────────────────────────────────
        btn_bar = tk.Frame(main, bg="#1e1e1e")
        btn_bar.pack(side="bottom", fill="x", pady=(8, 0))

        buttons = [
            ("📋  Copiar",          self._copy_text),
            ("🗑️  Limpiar",         self._clear_text),
            ("💾  Guardar como...", self._save_as),
            ("⚙️  Configurar",      self._open_settings),
        ]
        for text, cmd in buttons:
            tk.Button(
                btn_bar, text=text, command=cmd,
                bg="#3a3a3a", fg="#e0e0e0",
                relief="flat", padx=12, pady=4, cursor="hand2",
                font=("Segoe UI", 9),
                activebackground="#4a4a4a", activeforeground="#ffffff",
            ).pack(side="left", padx=(0, 8))

        # ── Status bar ───────────────────────────────────────────────────
        status_frame = tk.Frame(main, bg="#2d2d2d", height=34)
        status_frame.pack(side="bottom", fill="x", pady=(8, 0))
        status_frame.pack_propagate(False)

        self._counter_lbl = tk.Label(
            status_frame,
            text="", bg="#2d2d2d", fg="#808080",
            font=("Segoe UI", 9),
            anchor="e",
        )
        self._counter_lbl.pack(side="right", padx=10)

        self._status_lbl = tk.Label(
            status_frame,
            text="", bg="#2d2d2d", fg=self.STATUS_COLOR["idle"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self._status_lbl.pack(side="left", padx=10, fill="x", expand=True)

        # ── Model-loading bar (hidden unless a model is loading) ─────────
        self._progress_frame = tk.Frame(main, bg="#1e1e1e")
        self._progress_lbl = tk.Label(
            self._progress_frame,
            text="", bg="#1e1e1e", fg="#dcdcaa",
            font=("Segoe UI", 9),
        )
        self._progress_lbl.pack(anchor="w")
        self._progress_bar = tk.Frame(self._progress_frame, bg="#2d2d2d", height=3)
        self._progress_bar.pack(fill="x", pady=(2, 0))
        self._progress_fill = tk.Frame(self._progress_bar, bg="#4ec9b0")
        self._progress_fill.place(relheight=1, relwidth=0)

        # ── Text area: ONLY dictated text, freely editable ───────────────
        self._text_frame = tk.Frame(main, bg="#2d2d2d")
        self._text_frame.pack(side="top", fill="both", expand=True)

        self._text = tk.Text(
            self._text_frame,
            bg="#1a1a1a", fg="#e0e0e0",
            insertbackground="#4ec9b0",
            font=("Segoe UI", 11),
            wrap="word",
            relief="flat",
            padx=12, pady=12,
            spacing1=2, spacing3=2,
            undo=True,
            width=1, height=1,  # real size comes from the window, not the font
        )
        scroll = tk.Scrollbar(
            self._text_frame, command=self._text.yview,
            bg="#2d2d2d", troughcolor="#1a1a1a",
        )
        scroll.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)
        self._text.configure(yscrollcommand=scroll.set)

        # Never let the window shrink below what the button bar needs.
        self.update_idletasks()
        self.minsize(btn_bar.winfo_reqwidth() + 20, 260)

        self._refresh_status()

    # ═══════════════════════════════════════════════════════════════════════
    # Cross-thread hand-over
    # ═══════════════════════════════════════════════════════════════════════

    def _post(self, func, *args) -> None:
        """Run ``func(*args)`` on the Tk thread. Safe to call from any thread."""
        self._events.put((func, args))

    def _poll_events(self) -> None:
        if not self._running:
            return
        try:
            while True:
                func, args = self._events.get_nowait()
                try:
                    func(*args)
                except Exception:
                    logger.exception("Posted call %r failed", func)
        except queue.Empty:
            pass
        self.after(self._POLL_MS, self._poll_events)

    # ═══════════════════════════════════════════════════════════════════════
    # Hotkey
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

    def _on_hotkey(self) -> None:
        """Called by pynput on its own thread."""
        self._post(self._handle_hotkey)

    def _handle_hotkey(self) -> None:
        """React to the hotkey based on the current state."""
        logger.info("Hotkey pressed, state: %s", self._state)
        if self._state == "recording":
            self._stop_and_transcribe()
        elif self._state == "transcribing":
            # Deliberately ignored: queuing it would start a recording by
            # surprise minutes later, when nobody is watching.
            sounds.play("error")
            self._flash("⏳  Aún transcribiendo — espera al aviso para volver a grabar")
        else:  # idle, done, error
            self._start_recording()

    # ═══════════════════════════════════════════════════════════════════════
    # Status bar
    # ═══════════════════════════════════════════════════════════════════════

    def _set_state(self, state: str, detail: str = "") -> None:
        """Change the state and repaint the status bar."""
        logger.debug("State: %s → %s (%s)", self._state, state, detail)
        self._state = state
        self._state_detail = detail
        self._refresh_status()

    def _status_text(self) -> str:
        state, hotkey = self._state, config.HOTKEY
        if state == "recording":
            return (
                f"🔴  Grabando... {self._recorder.recording_duration:.1f}s"
                f" — {hotkey} para detener"
            )
        if state == "transcribing":
            return f"🟡  {self._transcribing_note or 'Transcribiendo...'}"
        if state == "done":
            return (
                f"✅  {self._state_detail or 'Listo'} — "
                f"{self._last_audio_secs:.1f}s de audio · "
                f"{self._last_chars} caracteres · "
                f"{self._last_proc_secs:.1f}s de proceso"
            )
        if state == "error":
            return f"❌  {self._state_detail or 'Error desconocido'}"
        text = f"🟢  Listo — presiona {hotkey} para grabar"
        if self._model_asleep and not self._transcriber.is_model_loaded:
            text += "  ·  💤 modelo en reposo"
        return text

    def _refresh_status(self) -> None:
        """Repaint the status bar from the current state (never changes it)."""
        self._status_lbl.configure(
            text=self._status_text(),
            fg=self.STATUS_COLOR.get(self._state, "#e0e0e0"),
        )
        self._force_paint()

    def _flash(self, msg: str, duration_ms: int = 2_500) -> None:
        """Show a temporary message in the status bar.

        Only one restore timer is ever pending: a new flash cancels the
        previous restore, otherwise stacked restores repaint stale text.
        """
        self._status_lbl.configure(text=msg, fg="#4ec9b0")
        self._force_paint()
        self._cancel_timer("_flash_restore_id")
        self._flash_restore_id = self.after(duration_ms, self._refresh_status)

    def _force_paint(self) -> None:
        """Force immediate window repaint via Win32 API (works without focus)."""
        self.update_idletasks()
        try:
            ctypes.windll.user32.UpdateWindow(self.winfo_id())
        except Exception:
            pass

    def _cancel_timer(self, attr: str) -> None:
        """Cancel the ``after`` timer stored in ``self.<attr>`` (if any)."""
        timer_id = getattr(self, attr)
        if timer_id is not None:
            try:
                self.after_cancel(timer_id)
            except Exception:
                pass
            setattr(self, attr, None)

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

        The raw detail always goes to voz.log; this only shapes what the
        status bar shows.
        """
        low = (detail or "").lower()
        for patterns, friendly in App._ERROR_PATTERNS:
            if any(p in low for p in patterns):
                return friendly
        return (detail or "Error desconocido")[:120]

    # ═══════════════════════════════════════════════════════════════════════
    # Dictation cycle
    # ═══════════════════════════════════════════════════════════════════════

    def _start_recording(self) -> None:
        """IDLE / DONE / ERROR → RECORDING"""
        self._cancel_timer("_return_to_idle_id")
        self._cancel_timer("_unload_timer_id")  # user is active again
        try:
            self._recorder.start()
        except Exception as exc:
            logger.error("Could not start recording: %s", exc, exc_info=True)
            self._on_error(str(exc))
            return

        sounds.play("start")
        self._set_state("recording")
        self._recording_tick_id = self.after(self._REC_TICK_MS, self._tick_recording)

        # If the model was unloaded while idle, reload it NOW, while the
        # user talks, so it is ready by the time they stop.
        self._load_model_async()

    def _tick_recording(self) -> None:
        """Refresh the live seconds counter while recording."""
        self._recording_tick_id = None
        if self._state != "recording" or not self._running:
            return
        self._refresh_status()
        self._recording_tick_id = self.after(self._REC_TICK_MS, self._tick_recording)

    def _stop_and_transcribe(self) -> None:
        """RECORDING → TRANSCRIBING (stop + resample + transcribe off-thread).

        recorder.stop() may take hundreds of ms on long dictations (buffer
        concat + resample) — never run it on the UI thread.
        """
        self._cancel_timer("_recording_tick_id")
        sounds.play("stop")
        self._transcribing_note = ""
        self._set_state("transcribing")

        self._transcription_thread = threading.Thread(
            target=self._worker_transcribe,
            daemon=True,
        )
        self._transcription_thread.start()

    def _worker_transcribe(self) -> None:
        """Stop the recorder and run faster-whisper — on a background thread."""
        transcriber = self._transcriber
        try:
            audio = self._recorder.stop()
        except Exception as exc:
            logger.exception("Could not stop the recorder")
            self._post(self._on_error, f"Error al detener la grabación: {exc}")
            return

        if len(audio) == 0:
            self._post(self._on_nothing_to_paste, "No se capturó audio")
            return

        try:
            if not transcriber.is_model_loaded:
                self._post(
                    self._show_transcribing,
                    "Cargando modelo..."
                    if transcriber.is_model_cached()
                    else "Descargando modelo (~1.5 GB)...",
                )
                transcriber.preload()

            audio_secs = len(audio) / config.SAMPLE_RATE
            self._post(
                self._show_transcribing,
                f"Transcribiendo {audio_secs:.1f}s de audio...",
            )
            t0 = time.monotonic()
            result = transcriber.transcribe(audio)
            proc_secs = time.monotonic() - t0
        except Exception as exc:
            logger.exception("Transcription failed")
            self._post(self._on_error, str(exc))
            return

        self._post(self._on_transcription_done, result, proc_secs)

    def _show_transcribing(self, note: str) -> None:
        """Show what the worker is doing right now (Tk thread only)."""
        if self._state != "transcribing":
            return
        self._transcribing_note = note
        self._refresh_status()

    def _on_transcription_done(self, result, proc_secs: float = 0.0) -> None:
        """TRANSCRIBING → DONE: copy, paste, save, show."""
        self._model_asleep = False  # transcribing reloads the model if needed
        text = result.text.strip()
        if not text:
            self._on_nothing_to_paste("No se detectó voz")
            return

        self._session_count += 1
        self._last_audio_secs = result.duration
        self._last_chars = len(text)
        self._last_proc_secs = proc_secs
        logger.info(
            "Dictation done: %.1fs audio, %d chars, %.1fs processing",
            result.duration, len(text), proc_secs,
        )

        # ── Clipboard (auto-paste needs the text there too) ──────────────
        outcome = "Listo"
        if config.AUTO_COPY or config.AUTO_PASTE:
            if not self._clipboard.copy(text):
                outcome = "No se pudo copiar"
            elif (
                config.AUTO_PASTE
                and not self._window_has_focus()
                and self._clipboard.paste()
            ):
                outcome = "Pegado"
            else:
                outcome = "Copiado"

        # ── Auto-save (background thread – don't block the GUI) ──────────
        if config.AUTO_SAVE:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            threading.Thread(
                target=self._worker_save,
                args=(self._storage, result, f"dictado_{timestamp}"),
                daemon=True,
            ).start()

        self._append_text(text)
        self._counter_lbl.configure(
            text=f"Dictados: {self._session_count}  ·  Último: {result.duration:.1f}s",
        )

        sounds.play("done")
        self._set_state("done", outcome)
        self._return_to_idle_id = self.after(self._DONE_MS, self._go_idle)

    def _window_has_focus(self) -> bool:
        """True when Voz itself (or its settings dialog) has keyboard focus.

        Auto-paste is skipped then: Ctrl+V would land in our own text area,
        where the dictation is already being appended.
        """
        try:
            return self.focus_displayof() is not None
        except Exception:  # tkinter raises KeyError for some popup widgets
            return True

    def _worker_save(self, storage: Storage, result, stem: str) -> None:
        """Write the .txt / .json pair on a background thread."""
        try:
            storage.save(result, stem)
        except Exception as exc:
            logger.error("Auto-save failed: %s", exc)
            self._post(self._flash, f"⚠️  Auto-guardado falló: {exc}")

    def _on_nothing_to_paste(self, reason: str) -> None:
        """TRANSCRIBING → IDLE: silence, or nothing reached the microphone."""
        logger.warning("Nothing to paste: %s", reason)
        sounds.play("error")
        self._go_idle()
        self._flash(f"⚠️  {reason}")

    def _on_error(self, msg: str) -> None:
        """ANY → ERROR (friendly text in the bar, raw text in voz.log)."""
        logger.error("Dictation error: %s", msg)
        sounds.play("error")
        self._set_state("error", self._friendly_error(msg))
        self._apply_pending_settings()
        self._schedule_model_unload()

    def _go_idle(self) -> None:
        """DONE → IDLE"""
        self._return_to_idle_id = None
        self._set_state("idle")
        self._apply_pending_settings()
        self._schedule_model_unload()

    # ═══════════════════════════════════════════════════════════════════════
    # Text area & buttons
    # ═══════════════════════════════════════════════════════════════════════

    def _append_text(self, text: str) -> None:
        """Add a dictation as a new paragraph at the end of the text area."""
        if self._current_text():
            self._text.insert("end", "\n\n")
        self._text.insert("end", text)
        self._text.see("end")

    def _current_text(self) -> str:
        """What the text area shows right now — including the user's edits."""
        return self._text.get("1.0", "end-1c").strip()

    def _copy_text(self) -> None:
        text = self._current_text()
        if not text:
            return
        if self._clipboard.copy(text):
            self._flash("📋  ¡Copiado!")
        else:
            self._flash("❌  No se pudo copiar")

    def _clear_text(self) -> None:
        if not self._current_text():
            return
        if messagebox.askyesno("Limpiar", "¿Borrar todo el texto acumulado?"):
            self._text.delete("1.0", "end")
            self._flash("🗑️  Texto borrado")

    def _save_as(self) -> None:
        text = self._current_text()
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

    # ═══════════════════════════════════════════════════════════════════════
    # Settings
    # ═══════════════════════════════════════════════════════════════════════

    def _open_settings(self) -> None:
        SettingsWindow(self, on_save=self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        """Apply new settings now, or right after the running dictation.

        Swapping Recorder or Transcriber mid-cycle would orphan an open mic
        stream or an in-flight model.
        """
        if self._state in ("recording", "transcribing"):
            self._pending_settings = True
            self._flash("⚙️  Guardado — se aplicará al terminar el dictado")
            return
        self._apply_settings()

    def _apply_pending_settings(self) -> None:
        if self._pending_settings:
            self._pending_settings = False
            self._apply_settings()

    def _apply_settings(self) -> None:
        """Recreate the modules that depend on changed config values."""
        if self._recorder.device != config.MICROPHONE_DEVICE:
            self._recorder = Recorder(device=config.MICROPHONE_DEVICE)
        if self._transcriber.model_name != config.MODEL:
            self._transcriber.unload()
            self._transcriber = Transcriber()
            self._model_asleep = False
            self._load_model_async(show_progress=True)
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

    # ═══════════════════════════════════════════════════════════════════════
    # Model loading / idle unload
    # ═══════════════════════════════════════════════════════════════════════

    def _load_model_async(self, show_progress: bool = False) -> None:
        """Load the Whisper model on a background thread (no-op if loaded).

        ``show_progress`` adds the loading bar and the "Modelo listo"
        message; without it the load is silent (warm-up while recording).
        """
        transcriber = self._transcriber
        if transcriber.is_model_loaded:
            return
        if show_progress:
            self._show_progress(
                "Cargando modelo..."
                if transcriber.is_model_cached()
                else "Descargando modelo (~1.5 GB)..."
            )

        def _load() -> None:
            try:
                transcriber.preload()
                ok = True
            except Exception as exc:
                logger.warning("Model load failed (will retry on dictation): %s", exc)
                ok = False
            self._post(self._on_model_loaded, transcriber, ok, show_progress)

        threading.Thread(target=_load, daemon=True).start()

    def _on_model_loaded(self, transcriber: Transcriber, ok: bool, announce: bool) -> None:
        """Model finished loading (Tk thread).

        Repaints from the state as it is NOW — the user may have started
        recording while the model was loading.
        """
        if announce:
            self._hide_progress()
        if not ok or transcriber is not self._transcriber:
            return
        self._model_asleep = False
        self._refresh_status()
        if announce:
            self._flash("✅  Modelo listo")
        if self._state not in ("recording", "transcribing"):
            self._schedule_model_unload()

    def _schedule_model_unload(self) -> None:
        """(Re)arm the idle timer that frees the model from RAM (~1.5 GB)."""
        self._cancel_timer("_unload_timer_id")
        minutes = config.MODEL_UNLOAD_MIN
        if minutes <= 0 or not self._transcriber.is_model_loaded:
            return
        self._unload_timer_id = self.after(minutes * 60_000, self._unload_model_now)

    def _unload_model_now(self) -> None:
        """Free the model after N idle minutes (config.MODEL_UNLOAD_MIN)."""
        self._unload_timer_id = None
        if (
            self._state in ("recording", "transcribing")
            or not self._transcriber.is_model_loaded
        ):
            return
        self._transcriber.unload()
        self._model_asleep = True
        logger.info(
            "Model unloaded after %d idle minute(s)", config.MODEL_UNLOAD_MIN
        )
        self._flash(
            "🛌  Modelo en reposo — se recarga solo al grabar",
            duration_ms=5_000,
        )

    def _show_progress(self, msg: str) -> None:
        """Show the animated model-loading bar above the text area."""
        self._hide_progress()
        self._progress_lbl.configure(text=msg)
        self._progress_frame.pack(
            side="top", fill="x", pady=(0, 6), before=self._text_frame
        )
        self._animate_progress(0)

    def _animate_progress(self, step: int) -> None:
        self._progress_fill.place(relwidth=0.15 + (step % 100) / 100.0 * 0.4)
        self._progress_id = self.after(80, self._animate_progress, step + 1)

    def _hide_progress(self) -> None:
        self._cancel_timer("_progress_id")
        self._progress_frame.pack_forget()

    # ═══════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def _on_close(self) -> None:
        """Close button → stop everything and exit.

        Worker threads are daemons and only talk to the UI through
        ``_post()``, so nothing has to be joined here.
        """
        self._running = False
        for timer in (
            "_recording_tick_id",
            "_flash_restore_id",
            "_return_to_idle_id",
            "_unload_timer_id",
            "_progress_id",
        ):
            self._cancel_timer(timer)

        if self._recorder.is_recording:
            # Off the UI thread: stop() may take a while on long dictations.
            threading.Thread(target=self._stop_recorder_quietly, daemon=True).start()

        if hasattr(self, "_hotkey"):
            self._hotkey.stop()

        self.destroy()

    def _stop_recorder_quietly(self) -> None:
        try:
            self._recorder.stop()
        except Exception:
            logger.debug("Recorder stop during close failed", exc_info=True)

    def run(self) -> None:
        """Show the window, start loading the model, run the event loop."""
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))

        self._load_model_async(show_progress=True)

        try:
            self.mainloop()
        except KeyboardInterrupt:
            self._on_close()
        finally:
            logger.info("Application shut down")


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
        app.after(150, app._open_settings)

    app.run()
