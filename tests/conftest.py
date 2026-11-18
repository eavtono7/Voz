"""
Shared test safety net.

Voz beeps, writes to the clipboard, sends Ctrl+V to whatever window has the
focus and loads a 1.5 GB model. None of that may ever really happen while
the test suite runs on a developer's machine, so those side effects are
neutralised for every test. Individual tests still patch these again when
they want to assert on them.
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _no_real_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    import pynput.keyboard
    import pyperclip

    import core.sounds
    from core.transcriber import Transcriber

    # The app warms the model up in the background when recording starts:
    # never load the real 1.5 GB model from a unit test.
    monkeypatch.setattr(Transcriber, "preload", lambda self: None)
    monkeypatch.setattr(core.sounds, "_beep", lambda tones: None)
    monkeypatch.setattr(pyperclip, "copy", mock.MagicMock())
    monkeypatch.setattr(pynput.keyboard, "Controller", mock.MagicMock())
