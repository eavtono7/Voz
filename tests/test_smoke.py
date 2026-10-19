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
