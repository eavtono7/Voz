"""
Clipboard operations: copy via pyperclip, paste via a simulated Ctrl+V.

Abstracts away the libraries so the rest of the codebase never depends
on pyperclip or pynput's keyboard controller directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Clipboard:
    """Copy text to the system clipboard and paste it into the focused app."""

    @staticmethod
    def copy(text: str) -> bool:
        """Copy *text* to the clipboard.

        Returns True on success, False on failure (logged).
        """
        if not text:
            logger.warning("Empty text – skipping clipboard copy")
            return False

        try:
            import pyperclip

            pyperclip.copy(text)
            logger.info("Copied %d characters to clipboard", len(text))
            return True
        except ImportError:
            logger.warning("pyperclip not installed – clipboard unavailable")
            return False
        except Exception as exc:
            logger.error("Failed to copy to clipboard: %s", exc)
            return False

    @staticmethod
    def paste() -> bool:
        """Send Ctrl+V to whatever application has the keyboard focus.

        Returns True if the keystroke was sent, False on failure (logged).
        """
        try:
            from pynput.keyboard import Controller, Key, KeyCode

            keyboard = Controller()
            v_key = KeyCode.from_vk(0x56)  # physical V: independent of layout
            with keyboard.pressed(Key.ctrl):
                keyboard.press(v_key)
                keyboard.release(v_key)
            logger.info("Sent Ctrl+V to the focused application")
            return True
        except Exception as exc:
            logger.error("Failed to paste: %s", exc)
            return False
