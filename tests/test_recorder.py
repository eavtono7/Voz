"""
Tests for core.recorder — samplerate detection, stop ordering, error paths.

All sounddevice interaction is faked; no microphone is required.
"""

from __future__ import annotations

import numpy as np
import pytest

import sounddevice as sd

import core.config as config
import core.recorder as rec_mod
from core.recorder import Recorder, RecorderError


@pytest.fixture(autouse=True)
def _fixed_target_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate from config mutation leaks (e.g. other tests setting 48000)."""
    monkeypatch.setattr(config, "SAMPLE_RATE", 16000)
    monkeypatch.setattr(config, "CHANNELS", 1)


class _FakeStream:
    """Stand-in for sd.InputStream.

    Optional ``_frames_on_stop`` kwarg: frames the device flushes when its
    stream is stopped (models real driver behaviour and Race fixes).
    """

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        for frame in self.kwargs.get("_frames_on_stop", []):
            self.kwargs["callback"](frame, frame.shape[0], None, None)

    def close(self) -> None:
        self.closed = True


def _patch_audio(monkeypatch, native_sr: int = 16000) -> list[_FakeStream]:
    streams: list[_FakeStream] = []

    def fake_stream(**kwargs) -> _FakeStream:
        s = _FakeStream(**kwargs)
        streams.append(s)
        return s

    monkeypatch.setattr(sd, "InputStream", fake_stream)
    monkeypatch.setattr(
        sd,
        "query_devices",
        lambda device=None, kind=None: {"default_samplerate": float(native_sr)},
    )
    return streams


# ── Samplerate detection (Fix 2) ───────────────────────────────────────────────


class TestDetectSamplerate:
    def test_default_device_queries_input_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple] = []

        def fake_query_devices(device=None, kind=None):
            calls.append((device, kind))
            if device is None:
                return {"default_samplerate": 48000.0}
            raise AssertionError("device path should not be used")

        monkeypatch.setattr(sd, "query_devices", fake_query_devices)

        r = Recorder()

        assert r.samplerate == 48000
        assert calls == [(None, "input")]

    def test_specific_device_uses_that_device(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple] = []

        def fake_query_devices(device=None, kind=None):
            calls.append((device, kind))
            return {"default_samplerate": 44100.0}

        monkeypatch.setattr(sd, "query_devices", fake_query_devices)

        r = Recorder(device=3)

        assert r.samplerate == 44100
        assert calls == [(3, None)]

    def test_falls_back_to_target_rate_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_query_devices(*args, **kwargs):
            raise RuntimeError("PortAudio exploded")

        monkeypatch.setattr(sd, "query_devices", broken_query_devices)

        r = Recorder()

        assert r.samplerate == config.SAMPLE_RATE


# ── Start / stop lifecycle (Fix 5) ────────────────────────────────────────────


class TestStartStop:
    def test_start_failure_resets_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_stream(**kwargs):
            raise Exception("device busy")

        monkeypatch.setattr(sd, "InputStream", broken_stream)
        monkeypatch.setattr(
            sd, "query_devices",
            lambda device=None, kind=None: {"default_samplerate": 16000.0},
        )

        r = Recorder()

        with pytest.raises(RecorderError):
            r.start()
        assert r.is_recording is False

    def test_stop_flushes_final_block_after_teardown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The real device can deliver one last callback during stream.stop();
        # it must be included in the returned audio.
        late = np.ones((64, 1), dtype=np.float32)
        injector: dict = {}

        def fake_stream(**kwargs) -> _FakeStream:
            kwargs["_frames_on_stop"] = [late]
            injector["obj"] = _FakeStream(**kwargs)
            return injector["obj"]

        monkeypatch.setattr(sd, "InputStream", fake_stream)
        monkeypatch.setattr(
            sd, "query_devices",
            lambda device=None, kind=None: {"default_samplerate": 16000.0},
        )

        r = Recorder()
        r.start()
        audio = r.stop()

        assert injector["obj"].stopped is True
        assert injector["obj"].closed is True
        assert audio.shape == (64,)
        assert bool(np.all(audio == 1.0))
        assert r.is_recording is False

    def test_stop_ignores_when_not_recording(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_audio(monkeypatch)
        r = Recorder()
        empty = r.stop()
        assert empty.size == 0
        assert empty.dtype == np.float32

    def test_double_start_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        streams = _patch_audio(monkeypatch)
        r = Recorder()
        r.start()
        r.start()  # second call must not open a second stream
        assert len(streams) == 1
        assert r.is_recording is True

    def test_stop_clears_buffer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_audio(monkeypatch)
        r = Recorder()
        r.start()
        frame = np.zeros((128, 1), dtype=np.float32)
        r._callback(frame, 128, None, None)
        r.stop()
        assert not r._buffer


class TestResampleOnStop:
    def test_delegates_to_core_audio(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[int, int]] = []

        def fake_resample(audio, orig_sr, target_sr):
            calls.append((orig_sr, target_sr))
            return np.full(10, 7.0, dtype=np.float32)

        monkeypatch.setattr(rec_mod, "resample", fake_resample)

        def fake_query_devices(device=None, kind=None):
            return {"default_samplerate": 48000.0}

        monkeypatch.setattr(sd, "query_devices", fake_query_devices)

        injector: dict = {}

        def fake_stream(**kwargs) -> _FakeStream:
            injector["obj"] = _FakeStream(**kwargs)
            return injector["obj"]

        monkeypatch.setattr(sd, "InputStream", fake_stream)

        r = Recorder()
        assert r.samplerate == 48000
        r.start()
        injector["obj"].kwargs["callback"](
            np.ones((480, 1), dtype=np.float32), 480, None, None
        )
        audio = r.stop()

        assert injector["obj"].kwargs["callback"].__self__ is r
        assert calls == [(48000, config.SAMPLE_RATE)]
        assert audio.shape == (10,)
