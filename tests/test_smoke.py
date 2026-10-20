"""
Smoke / integration tests — verify all modules import and core classes work.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class TestImports:
    def test_core_imports(self) -> None:
        from core import config
        from core.models import Segment, TranscriptionResult
        from core.recorder import Recorder, RecorderError
        from core.transcriber import Transcriber, TranscriberError
        from core.clipboard import Clipboard
        from core.storage import Storage, StorageError

        assert config.MODEL == "turbo"

    def test_gui_imports(self) -> None:
        from gui.hotkey_listener import HotkeyListener, HotkeyListenerError
        from gui.settings_window import SettingsWindow

        assert HotkeyListener is not None
        assert SettingsWindow is not None


class TestStateMachine:
    def _make_app(self):
        import gc
        import logging

        logging.disable(logging.CRITICAL)

        import tkinter as tk
        from unittest import mock

        import core.config as config

        with mock.patch.object(tk.Tk, "mainloop"):
            with mock.patch.object(config, "CONFIG_PATH", Path("/nonexistent/config.json")):
                config.CONFIG_PATH = Path("/nonexistent/config.json")

                from gui.dictation_app import App
                from gui.hotkey_listener import HotkeyListener

                with mock.patch.object(HotkeyListener, "start"):
                    with mock.patch.object(HotkeyListener, "stop"):
                        # This Python/Tcl build intermittently fails to init
                        # a fresh Tk interpreter in long-lived processes
                        # (transient "couldn't read … auto.tcl"/ttk errors).
                        # Previous roots' interps are kept alive until Python
                        # GC runs, so collect first and retry once on
                        # TclError during App(root) creation.
                        last_exc: BaseException | None = None
                        for attempt in range(2):
                            try:
                                gc.collect()
                                app = App()
                                return app
                            except tk.TclError as exc:
                                last_exc = exc
                                logging.debug(
                                    "Transient TclError creating App (attempt %d): %s",
                                    attempt + 1, exc,
                                )
                        assert last_exc is not None
                        raise last_exc

    def test_initial_state_is_idle(self) -> None:
        app = self._make_app()
        assert app._state == "idle"
        app.destroy()

    def test_hotkey_setup_creates_listener(self) -> None:
        app = self._make_app()
        assert hasattr(app, "_hotkey")
        from gui.hotkey_listener import HotkeyListener
        assert isinstance(app._hotkey, HotkeyListener)
        app.destroy()

    def test_recorder_created(self) -> None:
        app = self._make_app()
        assert app._recorder is not None
        assert app._recorder.is_recording is False
        app.destroy()


class TestHotkeyStateMachine:
    """Fix 4 + Fix 6/7: hotkey handling across states, via the event queue."""

    def _make_app(self):
        return TestStateMachine._make_app(self)

    def test_hotkey_in_idle_starts_recording(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"):
                app._handle_hotkey()
                assert app._state == "recording"
        finally:
            app.destroy()

    def test_hotkey_reaches_state_machine_via_queue(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"):
                app._on_hotkey()  # posts from "pynput thread" (main thread here)
                app._poll_events()  # drive one poll cycle manually
                assert app._state == "recording"
        finally:
            app.destroy()

    def test_hotkey_in_done_cancels_idle_transition_and_records(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"):
                app._return_to_idle_id = app.after(10_000, lambda: None)
                app._set_state("done", detail="2.5")
                app._handle_hotkey()
                assert app._state == "recording"
                assert app._return_to_idle_id is None
        finally:
            app.destroy()

    def test_hotkey_ignored_while_transcribing(self) -> None:
        app = self._make_app()
        try:
            app._set_state("transcribing")
            app._handle_hotkey()
            assert app._state == "transcribing"  # dropped, no crash
        finally:
            app.destroy()

    def test_transcripts_survive_but_status_logs_do_not(self) -> None:
        app = self._make_app()
        try:
            app._transcripts.append("hola mundo")
            assert app._current_transcripts() == "hola mundo"
            assert app._current_transcripts() not in app._text.get("1.0", "end-1c")
        finally:
            app.destroy()


class TestFeedback:
    """Live counters, friendly errors and rich done message."""

    def _make_app(self):
        return TestStateMachine._make_app(self)

    def test_recording_tick_updates_status(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            app._set_state("recording")
            with mock.patch.object(
                type(app._recorder),
                "recording_duration",
                new_callable=mock.PropertyMock,
                return_value=1.2,
            ):
                app._tick_recording()
            assert "1.2s" in app._status_lbl.cget("text")
            assert app._state == "recording"
        finally:
            app.destroy()

    def test_tick_ignores_when_not_recording(self) -> None:
        app = self._make_app()
        try:
            app._set_state("transcribing")
            before = app._status_lbl.cget("text")
            app._tick_recording()
            assert app._status_lbl.cget("text") == before
        finally:
            app.destroy()

    def test_transcribing_shows_audio_duration(self) -> None:
        app = self._make_app()
        try:
            app._set_state("transcribing")
            app._show_transcribing_duration(7.3)
            assert "7.3s de audio" in app._status_lbl.cget("text")
            assert app._state == "transcribing"
        finally:
            app.destroy()

    def test_done_message_full_context(self) -> None:
        import types
        from unittest import mock

        import core.config as config

        app = self._make_app()
        try:
            with mock.patch.object(config, "AUTO_COPY", False), \
                 mock.patch.object(config, "AUTO_SAVE", False), \
                 mock.patch.object(type(app._clipboard), "copy", return_value=True):
                result = types.SimpleNamespace(
                    text="hola mundo", duration=7.3, language="es"
                )
                app._on_transcription_done(result, 1.5)
            text = app._status_lbl.cget("text")
            assert "7.3s de audio" in text
            assert "10 caracteres" in text
            assert "1.5s de proceso" in text
            assert app._state == "done"
        finally:
            app.destroy()

    def test_friendly_error_mapping(self) -> None:
        from gui.dictation_app import App

        cases = {
            "Failed to open microphone (device=1): boom": "Micrófono no disponible",
            "[Errno -996] Invalid input device": "Micrófono no disponible",
            "Device is busy": "Micrófono en uso",
            "Cannot transcribe empty audio": "No se capturó audio",
            "'auto' is not a valid language code": "Idioma inválido",
            "Error downloading model from huggingface": "Error de red",
        }
        for raw, expected in cases.items():
            assert expected in App._friendly_error(raw), raw

        assert App._friendly_error("x" * 300) == "x" * 120  # truncated passthrough

    def test_error_state_uses_friendly_and_logs_raw(self) -> None:
        app = self._make_app()
        try:
            app._on_transcription_error("Unable to open microphone: boom")
            assert "Micrófono no disponible" in app._status_lbl.cget("text")
            assert app._state == "error"
            widget = app._text.get("1.0", "end-1c")
            assert "Unable to open microphone: boom" in widget  # raw kept
        finally:
            app.destroy()

    def test_flash_restore_cancels_previous(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            cancelled: list = []
            with mock.patch.object(
                app, "after_cancel", side_effect=lambda i: cancelled.append(i)
            ):
                app._flash("uno")
                first = app._flash_restore_id
                assert first is not None
                app._flash("dos")
                assert first in cancelled
                assert app._flash_restore_id != first
        finally:
            app.destroy()

    def test_close_cancels_feedback_timers(self) -> None:
        import types
        from unittest import mock

        app = self._make_app()
        cancelled: list = []
        with mock.patch.object(app, "after_cancel", side_effect=lambda i: cancelled.append(i)):
            app._set_state("recording")
            app._start_recording_tick()
            app._flash("algo")
            tick_id = app._recording_tick_id
            flash_id = app._flash_restore_id
            app._transcription_thread = types.SimpleNamespace(
                is_alive=lambda: False, join=lambda timeout=None: None
            )
            app._on_close()
            assert tick_id in cancelled
            assert flash_id in cancelled
        # destroy already done by _on_close


class TestTranscriberModel:
    def test_is_model_cached_does_not_crash(self) -> None:
        from core.transcriber import Transcriber

        t = Transcriber()
        result = t.is_model_cached()
        assert isinstance(result, bool)

    def test_is_model_loaded_initially_false(self) -> None:
        from core.transcriber import Transcriber

        t = Transcriber()
        assert t.is_model_loaded is False

    def test_model_name_defaults_to_config(self) -> None:
        from core.transcriber import Transcriber

        t = Transcriber()
        assert t.model_name == "turbo"


class TestConfigIntegration:
    def test_init_creates_dirs(self, tmp_path: Path) -> None:
        import core.config as config

        config.BASE_DIR = tmp_path
        config.init()

        assert config.MODEL_DIR.exists()
        assert config.DICTATIONS_DIR.exists()
