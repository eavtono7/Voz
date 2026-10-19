"""
Tests for core.audio — shared resampling utility.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.audio import resample


class TestResampleIdentity:
    def test_same_rate_returns_same_array(self) -> None:
        audio = np.arange(16000, dtype=np.float32) / 16000.0
        assert resample(audio, 16000, 16000) is audio


class TestResampleDown:
    def test_48k_to_16k_preserves_duration_and_frequency(self) -> None:
        sr = 48000
        t = np.arange(sr, dtype=np.float64) / sr
        audio = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)

        out = resample(audio, 48000, 16000)

        assert out.dtype == np.float32
        assert abs(len(out) - 16000) <= 2

        # A 440 Hz sine over 1 s has ~880 zero crossings; large drift would
        # indicate wrong rate math.
        crossings = int(np.sum(np.abs(np.diff(np.sign(out))) > 0))
        assert abs(crossings - 880) < 12


class TestResampleUp:
    def test_16k_to_48k_triples_samples(self) -> None:
        audio = np.random.default_rng(0).standard_normal(16000).astype(np.float32)
        out = resample(audio, 16000, 48000)
        assert abs(len(out) - 48000) <= 6
        assert out.dtype == np.float32


class TestResampleOddRatios:
    def test_44100_to_16000(self) -> None:
        audio = np.random.default_rng(1).standard_normal(44100).astype(np.float32)
        out = resample(audio, 44100, 16000)
        assert abs(len(out) - 16000) <= 4
        assert out.dtype == np.float32


class TestResampleValidation:
    def test_rejects_zero_rate(self) -> None:
        audio = np.zeros(8, dtype=np.float32)
        with pytest.raises(ValueError):
            resample(audio, 0, 16000)

    def test_rejects_negative_rate(self) -> None:
        audio = np.zeros(8, dtype=np.float32)
        with pytest.raises(ValueError):
            resample(audio, 16000, -1)

    def test_rejects_float_rate(self) -> None:
        audio = np.zeros(8, dtype=np.float32)
        with pytest.raises(ValueError):
            resample(audio, 16000.0, 16000)  # type: ignore[arg-type]
