"""
Tests for core.clipboard — text copy, auto-paste, failure modes.
"""

from __future__ import annotations

from unittest import mock

from core.clipboard import Clipboard


class TestClipboard:
    def test_copy_success(self) -> None:
        with mock.patch("pyperclip.copy") as mock_copy:
            result = Clipboard.copy("hola mundo")
            assert result is True
            mock_copy.assert_called_once_with("hola mundo")

    def test_copy_empty_text_returns_false(self) -> None:
        assert Clipboard.copy("") is False

    def test_copy_import_error_returns_false(self) -> None:
        with mock.patch.dict("sys.modules", {"pyperclip": None}):
            result = Clipboard.copy("texto")
            assert result is False

    def test_copy_general_exception_returns_false(self) -> None:
        with mock.patch("pyperclip.copy", side_effect=RuntimeError("fail")):
            result = Clipboard.copy("texto")
            assert result is False


class TestPaste:
    def test_paste_sends_ctrl_v(self) -> None:
        from pynput.keyboard import Key, KeyCode

        with mock.patch("pynput.keyboard.Controller") as controller_cls:
            keyboard = controller_cls.return_value
            assert Clipboard.paste() is True

            keyboard.pressed.assert_called_once_with(Key.ctrl)
            v_key = KeyCode.from_vk(0x56)
            keyboard.press.assert_called_once_with(v_key)
            keyboard.release.assert_called_once_with(v_key)

    def test_paste_failure_returns_false(self) -> None:
        with mock.patch("pynput.keyboard.Controller", side_effect=RuntimeError("no input")):
            assert Clipboard.paste() is False
