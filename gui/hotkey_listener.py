"""
Global hotkey listener using pynput.

Emits a callback when the configured key is released,
regardless of whether the application window is focused.

Uses ``on_release`` (not ``on_press``) to avoid key-repeat
triggering multiple events when the user holds the key.
A simple debounce prevents duplicate events within 300 ms.
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

    def start(self, hotkey: str = "F10") -> None:
        """Begin listening for *hotkey* (e.g. 'F10', 'F9')."""
        from pynput import keyboard

        self._key_name = hotkey.upper()
        key = getattr(keyboard.Key, self._key_name.lower(), None)

        if key is None:
            raise HotkeyListenerError(f"Unsupported hotkey: {hotkey}")

        self._key = key
        self._listener = keyboard.Listener(on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()
        logger.info("Hotkey listener started: %s", hotkey)

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
        """Stop and restart with a different hotkey."""
        self.stop()
        self.start(hotkey)
