"""
Short audio cues, so you know what Voz is doing without looking at it.

Voz is normally used while another window is focused: a beep is the only
feedback that recording really started, stopped, or that the text is ready.
"""

from __future__ import annotations

import logging
import threading

from core import config

logger = logging.getLogger(__name__)

# kind → sequence of (frequency Hz, duration ms)
_TONES: dict[str, tuple[tuple[int, int], ...]] = {
    "start": ((880, 90),),              # recording started
    "stop":  ((587, 90),),              # recording stopped, transcribing
    "done":  ((784, 80), (1047, 110)),  # text ready (copied / pasted)
    "error": ((330, 250),),             # something went wrong / ignored
}


def play(kind: str) -> None:
    """Play the cue for *kind* without blocking (no-op if sounds are off)."""
    if not config.SOUNDS:
        return
    tones = _TONES.get(kind)
    if tones is None:
        logger.warning("Unknown sound cue: %r", kind)
        return
    threading.Thread(target=_beep, args=(tones,), daemon=True).start()


def _beep(tones: tuple[tuple[int, int], ...]) -> None:
    try:
        import winsound  # Windows only; anywhere else the cue is skipped

        for freq, ms in tones:
            winsound.Beep(freq, ms)
    except Exception as exc:
        logger.debug("Sound cue unavailable: %s", exc)
