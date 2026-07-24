"""
Tests for core.clipboard — text copy, failure modes.
"""

from __future__ import annotations

from unittest import mock

import pytest

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
