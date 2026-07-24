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
                        app = App()
                        return app

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
