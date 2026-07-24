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

import logging
import threading
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
        "recording":    "🔴  Grabando... — presiona {} para detener",
        "transcribing": "🟡  Transcribiendo...",
        "copying":      "📋  Copiando al portapapeles...",
        "storing":      "💾  Guardando...",
        "done":         "✅  ¡Listo! — {:.1f}s transcritos",
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
        self._last_duration: float = 0.0
        self._session_count: int = 0

        # ── Core modules (no file I/O, no mic access on init) ────────────
        self._recorder = Recorder(device=config.MICROPHONE_DEVICE)
        self._transcriber = Transcriber()
        self._clipboard = Clipboard()
        self._storage = Storage(config.DICTATIONS_DIR)

        # ── Threading ────────────────────────────────────────────────────
        self._transcription_thread: threading.Thread | None = None

        # ── Build UI ─────────────────────────────────────────────────────
        logger.debug("Building UI...")
        self._build_ui()
        logger.debug("Applying theme...")
        self._apply_theme()
        logger.debug("Setting up events...")
        self._setup_events()
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
        banner = tk.Label(
            main,
            text=(
                "\u25A0  V O Z    D i c t a d o   p o r   v o z"
            ),
            bg="#1e1e1e",
            fg="#4ec9b0",
            font=("Consolas", 10, "bold"),
        )
        banner.pack(pady=(0, 6))

        sep = tk.Frame(main, bg="#3a3a3a", height=1)
        sep.pack(fill="x", pady=(0, 8))

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

    def _setup_events(self) -> None:
        """Bind custom virtual events (thread-safe communication)."""
        self.bind("<<HotkeyPressed>>", lambda _: self._handle_hotkey())

    def _on_hotkey(self) -> None:
        """Called by pynput on a background thread – schedule via thread-safe event."""
        logger.debug("_on_hotkey called, generating event")
        self.event_generate("<<HotkeyPressed>>")

    def _handle_hotkey(self) -> None:
        """React to hotkey based on current state."""
        logger.info("_handle_hotkey called, current state: %s", self._state)
        if self._state == "idle":
            self._start_recording()
        elif self._state == "recording":
            self._stop_and_transcribe()

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
        elif state == "recording":
            text = template.format(hotkey)
        elif state == "done":
            dur = detail if detail else self._last_duration
            try:
                text = template.format(float(dur))
            except (ValueError, TypeError):
                text = template.format(0.0)
        elif state == "error":
            text = template.format(detail or "Error desconocido")
        else:
            text = template

        self._status_lbl.configure(
            text=text,
            fg=self.STATUS_COLOR.get(state, "#e0e0e0"),
        )
        self.update_idletasks()  # Force UI update

    # ── Transitions ───────────────────────────────────────────────────────

    def _start_recording(self) -> None:
        """IDLE → RECORDING"""
        logger.info("_start_recording called")
        try:
            logger.debug("Calling recorder.start()")
            self._recorder.start()
            logger.info("Recorder started successfully")
            self._set_state("recording")
            self._log_status("🎙️  Grabación iniciada — habla ahora")
        except RecorderError as exc:
            logger.error("RecorderError: %s", exc, exc_info=True)
            self._set_state("error", str(exc))
            self._log_status(f"❌  Error: {exc}")
        except Exception as exc:
            logger.error("Unexpected error in _start_recording: %s", exc, exc_info=True)
            self._set_state("error", str(exc))
            self._log_status(f"❌  Error inesperado: {exc}")

    def _stop_and_transcribe(self) -> None:
        """RECORDING → TRANSCRIBING (recording stops, transcription thread starts)"""
        logger.info("_stop_and_transcribe called")
        try:
            logger.debug("Calling recorder.stop()")
            audio = self._recorder.stop()
            logger.info("Recorder stopped, audio length: %d samples", len(audio))
        except RecorderError as exc:
            logger.error("RecorderError in _stop_and_transcribe: %s", exc, exc_info=True)
            self._set_state("error", str(exc))
            self._log_status(f"❌  Error al detener: {exc}")
            return
        except Exception as exc:
            logger.error("Unexpected error in recorder.stop(): %s", exc, exc_info=True)
            self._set_state("error", str(exc))
            self._log_status(f"❌  Error inesperado: {exc}")
            return

        if len(audio) == 0:
            logger.warning("Audio is empty, returning to idle")
            self._set_state("idle")
            self._log_status("⚠️  No se capturó audio")
            return

        self._last_duration = len(audio) / config.SAMPLE_RATE
        logger.info("Setting state to transcribing, duration: %.2fs", self._last_duration)
        self._set_state("transcribing")
        self._log_status(f"🔄  Transcribiendo {self._last_duration:.1f}s de audio...")

        logger.debug("Starting transcription thread")
        self._transcription_thread = threading.Thread(
            target=self._worker_transcribe,
            args=(audio,),
            daemon=True,
        )
        self._transcription_thread.start()
        logger.info("Transcription thread started")

    def _worker_transcribe(self, audio) -> None:
        """Run faster-whisper in a background thread."""
        logger.info("_worker_transcribe started, audio samples: %d", len(audio))
        try:
            logger.debug("Calling transcriber.transcribe()")
            result = self._transcriber.transcribe(audio)
            logger.info("Transcription completed, text length: %d", len(result.text))
            self.after(0, self._on_transcription_done, result)
        except TranscriberError as exc:
            logger.exception("Transcription failed")
            self.after(0, self._on_transcription_error, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error in _worker_transcribe")
            self.after(0, self._on_transcription_error, str(exc))

    def _worker_save(self, result, filename) -> None:
        """Save transcription result in a background thread."""
        try:
            self._storage.save(result, filename)
        except Exception as exc:
            logger.error("Auto-save failed: %s", exc)
            self.after(0, self._flash, f"⚠️  Auto-guardado falló: {exc}")

    def _on_transcription_done(self, result) -> None:
        """TRANSCRIBING → COPYING → STORING → DONE"""
        logger.info("_on_transcription_done called, text: %s", result.text[:50] if result.text else "(empty)")
        self._session_count += 1
        dur = result.duration

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
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        self._set_state("done", detail=dur)
        self._log_status(f"✅  Transcripción completada ({dur:.1f}s)")
        self.after(2_000, self._return_to_idle)

    def _on_transcription_error(self, msg: str) -> None:
        """TRANSCRIBING → ERROR"""
        logger.error("_on_transcription_error called: %s", msg)
        self._set_state("error", msg)
        self._log_status(f"❌  Error de transcripción: {msg}")

    def _return_to_idle(self) -> None:
        """DONE → IDLE"""
        self._set_state("idle")

    def _log_status(self, msg: str) -> None:
        """Write a status message to the text area."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.insert("end", f"\n[{ts}] {msg}\n", "timestamp")
        self._text.see("end")
        self.update_idletasks()

    # ── Text area helpers ───────────────────────────────────────────────

    def _append_text(self, result) -> None:
        """Insert a new transcription block into the text widget."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.insert("end", f"\n[{ts}]  ({result.duration:.1f}s  {result.language})\n", "timestamp")
        self._text.insert("end", f"{result.text}\n", "text")
        self._text.see("end")

        self._counter_lbl.configure(
            text=f"Dictados hoy: {self._session_count}  ·  Último: {result.duration:.1f}s",
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Button actions
    # ═══════════════════════════════════════════════════════════════════════

    def _copy_text(self) -> None:
        text = self._text.get("1.0", "end-1c").strip()
        if not text:
            return
        if self._clipboard.copy(text):
            self._flash("📋  ¡Copiado!")
        else:
            self._flash("❌  No se pudo copiar")

    def _clear_text(self) -> None:
        if not self._text.get("1.0", "end-1c").strip():
            return
        if messagebox.askyesno("Limpiar", "¿Borrar todo el texto acumulado?"):
            self._text.delete("1.0", "end")
            self._counter_lbl.configure(text="")
            self._flash("🗑️  Texto borrado")

    def _save_as(self) -> None:
        text = self._text.get("1.0", "end-1c").strip()
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
        """Recreate modules that depend on changed config values."""
        self._recorder = Recorder(device=config.MICROPHONE_DEVICE)
        if self._transcriber.model_name != config.MODEL:
            self._transcriber = Transcriber()
        self._storage = Storage(config.DICTATIONS_DIR)
        try:
            self._hotkey.restart(config.HOTKEY)
        except HotkeyListenerError as exc:
            logger.error("Failed to restart hotkey: %s", exc)
        self._flash("⚙️  Configuración actualizada")

    def _flash_status(self, msg: str, color: str | None = None) -> None:
        """Update status bar and log the message atomically (prevents UI freeze)."""
        color = color or self.STATUS_COLOR.get(self._state, "#e0e0e0")
        self._status_lbl.configure(text=msg, fg=color)
        self._log_status(msg)

    def _flash(self, msg: str) -> None:
        """Show a temporary message in the status bar (2.5 s)."""
        self._status_lbl.configure(text=msg, fg="#4ec9b0")
        self.after(2_500, lambda: self._set_state(self._state))

    def _on_close(self) -> None:
        """Close button → stop recording if active and exit."""
        if self._state == "recording":
            try:
                self._recorder.stop()
            except Exception:
                pass

        if (
            self._transcription_thread is not None
            and self._transcription_thread.is_alive()
        ):
            self._transcription_thread.join(timeout=3)

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
        """Start background model loading so the first dictation is fast."""
        if self._transcriber.is_model_loaded:
            return

        def _load() -> None:
            try:
                self._transcriber.preload()
            except Exception as exc:
                logger.warning("Model preload failed (will retry on first dictation): %s", exc)

        threading.Thread(target=_load, daemon=True).start()


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
