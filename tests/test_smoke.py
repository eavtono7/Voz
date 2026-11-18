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

    def test_hotkey_during_transcribing_is_ignored(self) -> None:
        """No queued press: a recording must never start by surprise later."""
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start") as rec_start:
                app._set_state("transcribing")
                app._handle_hotkey()
                assert app._state == "transcribing"
                assert "transcribiendo" in app._status_lbl.cget("text").lower()

                app._go_idle()  # cycle ends: still nothing may start
                assert app._state == "idle"
                rec_start.assert_not_called()
        finally:
            app.destroy()

    def test_model_ready_right_before_recording_keeps_recording_state(self) -> None:
        """Regression (12-Nov log): F10 right after "Modelo listo".

        A delayed repaint used to force the state back to 'idle' while the
        microphone kept recording, so the next F10 "started" again instead
        of stopping.
        """
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"), \
                 mock.patch.object(
                     type(app._recorder),
                     "recording_duration",
                     new_callable=mock.PropertyMock,
                     return_value=0.4,
                 ):
                app._on_model_loaded(app._transcriber, True, True)
                assert app._flash_restore_id is not None  # "Modelo listo" showing
                app._handle_hotkey()
                assert app._state == "recording"

                app._refresh_status()  # what the pending restore timer runs
                assert app._state == "recording"
                assert "Grabando" in app._status_lbl.cget("text")
        finally:
            app.destroy()

    def test_recording_warms_up_an_unloaded_model(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"), \
                 mock.patch.object(app, "_load_model_async") as warm_up:
                app._handle_hotkey()
                warm_up.assert_called_once_with()
        finally:
            app.destroy()

    def test_error_state_hotkey_starts_new_dictation(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"):
                app._set_state("error", "boom")
                app._handle_hotkey()
                assert app._state == "recording"
        finally:
            app.destroy()



class TestTextArea:
    """The text area holds only dictations, and the user's edits count."""

    def _make_app(self):
        return TestStateMachine._make_app(self)

    def _dictate(self, app, text: str) -> None:
        import types
        from unittest import mock

        import core.config as config

        with mock.patch.object(config, "AUTO_COPY", False), \
             mock.patch.object(config, "AUTO_PASTE", False), \
             mock.patch.object(config, "AUTO_SAVE", False):
            app._on_transcription_done(
                types.SimpleNamespace(text=text, duration=2.0, language="es"), 0.5
            )

    def test_only_dictated_text_reaches_the_widget(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(type(app._recorder), "start"):
                app._handle_hotkey()              # recording
            app._set_state("transcribing")
            app._show_transcribing("Transcribiendo 2.0s de audio...")
            self._dictate(app, "hola mundo")
            self._dictate(app, "segundo dictado")
            app._on_error("Unable to open microphone: boom")

            assert app._text.get("1.0", "end-1c") == "hola mundo\n\nsegundo dictado"
        finally:
            app.destroy()

    def test_copy_button_uses_the_edited_text(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            self._dictate(app, "ola mundo")
            app._text.delete("1.0", "end")
            app._text.insert("1.0", "Hola, mundo.")  # user fixes the text

            with mock.patch.object(
                type(app._clipboard), "copy", return_value=True
            ) as copy:
                app._copy_text()
            copy.assert_called_once_with("Hola, mundo.")
        finally:
            app.destroy()

    def test_buttons_fit_in_the_minimum_window(self) -> None:
        app = self._make_app()
        try:
            min_width, min_height = app.minsize()
            assert min_width < 640 and min_height <= 300  # compact, not 800x800
            app.geometry(f"{min_width}x{min_height}")
            app.update()
            for button in app.winfo_children()[0].winfo_children()[0].winfo_children():
                right_edge = button.winfo_rootx() + button.winfo_width()
                assert right_edge <= app.winfo_rootx() + app.winfo_width()
                assert button.winfo_height() > 1, "button bar must stay visible"
        finally:
            app.destroy()


class TestAutoPaste:
    """Copy + Ctrl+V into the focused app once the text is ready."""

    def _make_app(self):
        return TestStateMachine._make_app(self)

    def _finish(self, app, *, text="hola mundo", copy=True, paste=True, focused=False):
        import types
        from unittest import mock

        import core.config as config

        clip = type(app._clipboard)
        with mock.patch.object(config, "AUTO_COPY", copy), \
             mock.patch.object(config, "AUTO_PASTE", paste), \
             mock.patch.object(config, "AUTO_SAVE", False), \
             mock.patch.object(app, "_window_has_focus", return_value=focused), \
             mock.patch.object(clip, "copy", return_value=True) as copy_mock, \
             mock.patch.object(clip, "paste", return_value=True) as paste_mock:
            app._on_transcription_done(
                types.SimpleNamespace(text=text, duration=3.0, language="es"), 1.0
            )
        return copy_mock, paste_mock

    def test_pastes_into_the_other_app(self) -> None:
        app = self._make_app()
        try:
            copy, paste = self._finish(app)
            copy.assert_called_once_with("hola mundo")
            paste.assert_called_once_with()
            assert "Pegado" in app._status_lbl.cget("text")
        finally:
            app.destroy()

    def test_no_paste_when_voz_itself_has_focus(self) -> None:
        app = self._make_app()
        try:
            copy, paste = self._finish(app, focused=True)
            copy.assert_called_once()
            paste.assert_not_called()
            assert "Copiado" in app._status_lbl.cget("text")
        finally:
            app.destroy()

    def test_paste_disabled_only_copies(self) -> None:
        app = self._make_app()
        try:
            copy, paste = self._finish(app, paste=False)
            copy.assert_called_once()
            paste.assert_not_called()
        finally:
            app.destroy()

    def test_paste_implies_copy(self) -> None:
        app = self._make_app()
        try:
            copy, paste = self._finish(app, copy=False, paste=True)
            copy.assert_called_once()
            paste.assert_called_once()
        finally:
            app.destroy()

    def test_silence_touches_nothing(self) -> None:
        """Empty transcription: clipboard is preserved, nothing is pasted."""
        app = self._make_app()
        try:
            app._set_state("transcribing")
            copy, paste = self._finish(app, text="   ")
            copy.assert_not_called()
            paste.assert_not_called()
            assert app._state == "idle"
            assert app._session_count == 0
            assert app._text.get("1.0", "end-1c") == ""
            assert "No se detectó voz" in app._status_lbl.cget("text")
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
            app._show_transcribing("Transcribiendo 7.3s de audio...")
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
                 mock.patch.object(config, "AUTO_PASTE", False), \
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

    def test_error_state_shows_friendly_message(self) -> None:
        app = self._make_app()
        try:
            app._on_error("Unable to open microphone: boom")
            assert "Micrófono no disponible" in app._status_lbl.cget("text")
            assert app._state == "error"
        finally:
            app.destroy()

    def test_flash_restore_keeps_the_error_message(self) -> None:
        """A temporary message must not turn the error into 'desconocido'."""
        app = self._make_app()
        try:
            app._on_error("Unable to open microphone: boom")
            app._flash("📋  ¡Copiado!")
            app._refresh_status()  # what the restore timer runs
            assert "Micrófono no disponible" in app._status_lbl.cget("text")
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
            app._recording_tick_id = app.after(60_000, lambda: None)
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


class TestModelUnload:
    """Idle TTL: the loaded model is freed from RAM when config allows."""

    def _make_app(self):
        return TestStateMachine._make_app(self)

    def test_schedule_when_enabled_and_loaded(self) -> None:
        import core.config as config
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(config, "MODEL_UNLOAD_MIN", 10), \
                 mock.patch.object(
                     type(app._transcriber),
                     "is_model_loaded",
                     new_callable=mock.PropertyMock,
                     return_value=True,
                 ):
                app._schedule_model_unload()
                assert app._unload_timer_id is not None
        finally:
            app.destroy()

    def test_no_schedule_when_disabled(self) -> None:
        import types

        import core.config as config
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(config, "MODEL_UNLOAD_MIN", 0):
                app._schedule_model_unload()
                assert app._unload_timer_id is None
        finally:
            app.destroy()

    def test_unload_now_frees_model(self) -> None:
        import core.config as config
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(config, "MODEL_UNLOAD_MIN", 10), \
                 mock.patch.object(
                     type(app._transcriber),
                     "is_model_loaded",
                     new_callable=mock.PropertyMock,
                     return_value=True,
                 ), \
                 mock.patch.object(type(app._transcriber), "unload") as unload:
                app._schedule_model_unload()  # arms the idle timer
                assert app._unload_timer_id is not None
                app._unload_model_now()
                unload.assert_called_once()
            assert app._unload_timer_id is None
            assert app._state == "idle"
        finally:
            app.destroy()

    def test_recording_cancels_pending_unload(self) -> None:
        import core.config as config
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(config, "MODEL_UNLOAD_MIN", 10), \
                 mock.patch.object(
                     type(app._transcriber),
                     "is_model_loaded",
                     new_callable=mock.PropertyMock,
                     return_value=True,
                 ):
                app._schedule_model_unload()
                timer_id = app._unload_timer_id
                assert timer_id is not None
                with mock.patch.object(type(app._recorder), "start"):
                    app._start_recording()
                assert app._unload_timer_id is None
        finally:
            app.destroy()

    def test_close_cancels_unload_timer(self) -> None:
        import types
        from unittest import mock

        app = self._make_app()
        cancelled: list = []
        with mock.patch.object(app, "after_cancel", side_effect=lambda i: cancelled.append(i)):
            app._unload_timer_id = app.after(60_000, lambda: None)
            unload_id = app._unload_timer_id
            app._transcription_thread = types.SimpleNamespace(
                is_alive=lambda: False, join=lambda timeout=None: None
            )
            app._on_close()
            assert unload_id in cancelled
        # destroy already done by _on_close

    def test_idle_status_shows_asleep_suffix(self) -> None:
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(
                type(app._transcriber),
                "is_model_loaded",
                new_callable=mock.PropertyMock,
                return_value=False,
            ):
                app._model_asleep = True
                app._set_state("idle")
                assert "reposo" in app._status_lbl.cget("text")

            with mock.patch.object(
                type(app._transcriber),
                "is_model_loaded",
                new_callable=mock.PropertyMock,
                return_value=True,
            ):
                app._on_model_loaded(app._transcriber, True, False)
                assert "reposo" not in app._status_lbl.cget("text")
                assert app._model_asleep is False
        finally:
            app.destroy()

    def test_unload_now_announces_and_marks_asleep(self) -> None:
        import core.config as config
        from unittest import mock

        app = self._make_app()
        try:
            with mock.patch.object(config, "MODEL_UNLOAD_MIN", 10), \
                 mock.patch.object(
                     type(app._transcriber),
                     "is_model_loaded",
                     new_callable=mock.PropertyMock,
                     return_value=True,
                 ), \
                 mock.patch.object(type(app._transcriber), "unload"):
                app._unload_model_now()
            assert app._model_asleep is True
            assert "Modelo en reposo" in app._status_lbl.cget("text")
            assert app._text.get("1.0", "end-1c") == ""
        finally:
            app.destroy()

    def test_done_clears_asleep_flag(self) -> None:
        import types

        import core.config as config
        from unittest import mock

        app = self._make_app()
        try:
            app._model_asleep = True
            with mock.patch.object(config, "AUTO_COPY", False), \
                 mock.patch.object(config, "AUTO_PASTE", False), \
                 mock.patch.object(config, "AUTO_SAVE", False):
                result = types.SimpleNamespace(
                    text="hola", duration=1.0, language="es"
                )
                app._on_transcription_done(result, 0.5)
            assert app._model_asleep is False
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
