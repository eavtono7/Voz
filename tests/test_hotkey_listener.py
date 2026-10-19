"""
Tests for gui.hotkey_listener — key validation and atomic restart.

pynput itself is faked so no real listener/hook is ever installed.
"""

from __future__ import annotations

import sys
import types

import pytest

import gui.hotkey_listener as hl
from gui.hotkey_listener import HotkeyListener, HotkeyListenerError


class _FakeListener:
    """Stand-in for pynput.keyboard.Listener."""

    def __init__(self, on_release=None, **kwargs) -> None:
        self.on_release = on_release
        self.daemon = None
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started and not self.stopped

    def stop(self) -> None:
        self.stopped = True


class _FakeKeyboard(types.ModuleType):
    def __init__(self, keys: dict) -> None:
        super().__init__("pynput.keyboard")
        self.Key = types.SimpleNamespace(**keys)
        self.Listener = _FakeListener


@pytest.fixture
def fake_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Replace pynput.keyboard with a controllable fake module.

    Both the sys.modules entry and the package attribute are patched:
    pynput.__init__ eagerly binds ``keyboard``, and ``from pynput import
    keyboard`` resolves through it once the package is already imported.
    """
    import pynput

    f10 = object()
    f9 = object()
    mod = _FakeKeyboard({"f10": f10, "f9": f9})
    monkeypatch.setitem(sys.modules, "pynput.keyboard", mod)
    monkeypatch.setattr(pynput, "keyboard", mod, raising=False)
    return mod


class TestIsSupported:
    def test_fkeys_supported(self, fake_keyboard: object) -> None:
        assert HotkeyListener.is_supported("F10") is True
        assert HotkeyListener.is_supported("f9") is True

    def test_letters_not_supported(self, fake_keyboard: object) -> None:
        assert HotkeyListener.is_supported("K") is False

    def test_empty_not_supported(self, fake_keyboard: object) -> None:
        assert HotkeyListener.is_supported("") is False
        assert HotkeyListener.is_supported("   ") is False


class TestStart:
    def test_start_unsupported_raises_without_listener(
        self, fake_keyboard: object
    ) -> None:
        l = HotkeyListener(callback=lambda: None)
        with pytest.raises(HotkeyListenerError):
            l.start("K")
        assert l._listener is None
        assert l._key_name is None

    def test_start_registers_release_callback(self, fake_keyboard: object) -> None:
        l = HotkeyListener(callback=lambda: None)
        l.start("F10")
        assert l._key_name == "F10"
        assert isinstance(l._listener, _FakeListener)
        # Bound methods are created per attribute access → compare parts.
        assert l._listener.on_release.__func__ is HotkeyListener._on_release
        assert l._listener.on_release.__self__ is l
        assert l._listener.started is True


class TestOnRelease:
    def test_matching_key_calls_callback(self, fake_keyboard: object) -> None:
        key = getattr(
            sys.modules["pynput.keyboard"].Key, "f10"
        )
        hits: list[int] = []
        l = HotkeyListener(callback=lambda: hits.append(1))
        l.start("F10")
        l._last_call = 0.0
        l._listener.on_release(key)
        assert hits == [1]

    def test_other_keys_ignored(self, fake_keyboard: object) -> None:
        f9 = getattr(sys.modules["pynput.keyboard"].Key, "f9")
        hits: list[int] = []
        l = HotkeyListener(callback=lambda: hits.append(1))
        l.start("F10")
        l._listener.on_release(f9)
        assert hits == []

    def test_debounce_blocks_rapid_repeats(self, fake_keyboard: object) -> None:
        key = getattr(sys.modules["pynput.keyboard"].Key, "f10")
        hits: list[int] = []
        l = HotkeyListener(callback=lambda: hits.append(1))
        l.start("F10")
        l._last_call = hl.time.monotonic()  # fresh release just happened
        l._listener.on_release(key)
        assert hits == []


class TestRestart:
    def test_restart_swaps_listener_and_stops_old(
        self, fake_keyboard: object
    ) -> None:
        l = HotkeyListener(callback=lambda: None)
        l.start("F10")
        old = l._listener

        l.restart("F9")

        assert l._key_name == "F9"
        assert l._listener is not old
        assert l._listener.started is True
        assert old.stopped is True  # old listener only stopped after swap

    def test_restart_same_key_is_noop(self, fake_keyboard: object) -> None:
        l = HotkeyListener(callback=lambda: None)
        l.start("F10")
        old = l._listener

        l.restart("F10")

        assert l._listener is old
        assert old.started is True

    def test_restart_unsupported_keeps_old_running(
        self, fake_keyboard: object
    ) -> None:
        l = HotkeyListener(callback=lambda: None)
        l.start("F10")
        old = l._listener

        with pytest.raises(HotkeyListenerError):
            l.restart("K")  # not a bindable key

        # Old listener must still be alive and config untouched
        assert l._listener is old
        assert l._key_name == "F10"
        assert old.stopped is False
        assert old.started is True


class TestStop:
    def test_stop_stops_listener(self, fake_keyboard: object) -> None:
        l = HotkeyListener(callback=lambda: None)
        l.start("F10")
        listener = l._listener
        l.stop()
        assert listener.stopped is True
