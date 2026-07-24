"""
Clipboard operations via pyperclip.

Abstracts away the clipboard library so the rest of the codebase
never depends on pyperclip directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Clipboard:
    """Copy text to the system clipboard."""

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
