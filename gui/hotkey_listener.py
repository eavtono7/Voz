"""
Global hotkey listener using pynput.

Emits a callback when the configured key is released,
regardless of whether the application window is focused.

Uses ``on_release`` (not ``on_press``) to avoid key-repeat
triggering multiple events when the user holds the key.
A simple debounce prevents duplicate events within 500 ms.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 500


class HotkeyListenerError(Exception):
    """Raised when the listener cannot be started."""


class HotkeyListener:
    """Listens for a global hotkey in a background thread.

    The *callback* is called from the pynput listener thread.
    Use ``tkinter.app.after(0, callback)`` to schedule work on the
    main thread.
    """

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._key_name: str | None = None
        self._key = None
        self._listener = None
        self._last_call: float = 0.0

    @staticmethod
    def is_supported(hotkey: str) -> bool:
        """Return True if *hotkey* names a key pynput can bind globally.

        Validates *before* saving config or stopping the running listener,
        so a bad choice can never leave the app without a hotkey.
        """
        try:
            from pynput import keyboard
        except Exception:  # ImportError and native backend failures
            return False
        name = (hotkey or "").strip().lower()
        return bool(name) and getattr(keyboard.Key, name, None) is not None

    def start(self, hotkey: str = "F10") -> None:
        """Begin listening for *hotkey* (e.g. 'F10', 'F9')."""
        from pynput import keyboard

        name = (hotkey or "").strip().upper()
        key = getattr(keyboard.Key, name.lower(), None) if name else None

        if key is None:
            raise HotkeyListenerError(f"Unsupported hotkey: {hotkey!r}")

        self._key_name = name
        self._key = key
        self._listener = keyboard.Listener(on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()
        logger.info("Hotkey listener started: %s", name)

    def _on_release(self, key) -> None:
        """Handle key-release events (ignores auto-repeat)."""
        if self._key is None or self._key_name is None:
            return

        if key == self._key:
            logger.debug("Hotkey %s released", self._key_name)
            now = time.monotonic()
            if (now - self._last_call) * 1000 < _DEBOUNCE_MS:
                logger.debug("Hotkey debounced (too soon)")
                return
            self._last_call = now
            logger.info("Hotkey callback executing")
            try:
                self._callback()
                logger.info("Hotkey callback completed")
            except Exception as exc:
                logger.error("Hotkey callback failed: %s", exc)

    def stop(self) -> None:
        """Shut down the listener."""
        if self._listener is not None and self._listener.is_alive():
            self._listener.stop()
            logger.info("Hotkey listener stopped")

    def restart(self, hotkey: str) -> None:
        """Switch to a different hotkey — atomically.

        The new listener is created and started FIRST; the running
        listener is only stopped after the new one is alive. If the new
        key is invalid, the old listener keeps working untouched.

        No-op if the key is unchanged.
        """
        hotkey = (hotkey or "").strip().upper()
        if hotkey == self._key_name:
            return

        replacement = HotkeyListener(self._callback)
        replacement.start(hotkey)  # raises → self untouched

        self.stop()
        self._listener = replacement._listener
        self._key = replacement._key
        self._key_name = replacement._key_name
        logger.info("Hotkey listener restarted: %s", hotkey)
