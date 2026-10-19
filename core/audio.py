"""
Audio utilities shared by Recorder and Transcriber.

Single source of truth for resampling, so it is never accidentally
implemented twice with different quality characteristics.
"""

from __future__ import annotations

import logging
from math import gcd

import numpy as np

logger = logging.getLogger(__name__)


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample a 1-D audio array from *orig_sr* to *target_sr*.

    Uses polyphase filtering (scipy.signal.resample_poly), which avoids
    the edge ringing of FFT-based resampling (signal.resample assumes a
    periodic signal) and handles arbitrary rate ratios cleanly.

    Returns:
        float32 1-D array at *target_sr*.

    Raises:
        ValueError if either rate is not a positive integer.
    """
    if not isinstance(orig_sr, int) or not isinstance(target_sr, int):
        raise ValueError(
            f"Sample rates must be int, got {orig_sr!r} and {target_sr!r}"
        )
    if orig_sr <= 0 or target_sr <= 0:
        raise ValueError(
            f"Sample rates must be positive, got {orig_sr} and {target_sr}"
        )

    if orig_sr == target_sr:
        return audio

    # signal.resample_poly wants small integer ratios (up, down)
    divisor = gcd(orig_sr, target_sr)
    up = target_sr // divisor
    down = orig_sr // divisor

    from scipy import signal

    resampled = signal.resample_poly(audio, up, down)
    logger.debug(
        "Resampled %d→%d Hz  %d→%d samples",
        orig_sr,
        target_sr,
        len(audio),
        len(resampled),
    )
    return resampled.astype(np.float32)
