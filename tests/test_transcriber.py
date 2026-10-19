"""
Tests for core.transcriber — language normalization, result assembly, errors.

The whisper model is faked; no model download happens.
"""

from __future__ import annotations

import types
from typing import Any, Dict

import numpy as np
import pytest

import core.config as config
from core.transcriber import Transcriber, TranscriberError, _normalize_language


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class TestNormalizeLanguage:
    @pytest.mark.parametrize(
        "value", ["auto", "AUTO", "Auto", "auto-detectar", "autodetectar", "", "  "]
    )
    def test_auto_variants_become_none(self, value: str) -> None:
        assert _normalize_language(value) is None

    def test_none_stays_none(self) -> None:
        assert _normalize_language(None) is None

    @pytest.mark.parametrize("value,expected", [("es", "es"), (" EN ", "en"), ("de", "de")])
    def test_iso_codes_pass_through(self, value: str, expected: str) -> None:
        assert _normalize_language(value) == expected


def _make_faked_instance(
    monkeypatch: pytest.MonkeyPatch,
    calls: Dict[str, Any],
) -> Transcriber:
    def fake_transcribe(audio: np.ndarray, **kwargs: Any):
        calls["audio"] = audio
        calls.update(kwargs)
        segments = iter(
            [_FakeSegment(0.0, 0.5, "hola"), _FakeSegment(0.5, 1.0, "mundo")]
        )
        return segments, types.SimpleNamespace(language="es")

    t = Transcriber()
    t._model = types.SimpleNamespace(transcribe=fake_transcribe)  # type: ignore[assignment]
    monkeypatch.setattr(Transcriber, "_load_model", lambda self: None)
    monkeypatch.setattr(config, "LANGUAGE", "es")
    return t


class TestTranscribeLanguage:
    def test_auto_config_maps_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, calls)
        monkeypatch.setattr(config, "LANGUAGE", "auto")  # as saved by settings

        result = t.transcribe(np.zeros(16000, dtype=np.float32))

        # Regression: passing 'auto' straight through crashed the tokenizer.
        assert calls["language"] is None
        assert result.text == "hola mundo"
        assert result.language == "es"

    def test_es_config_passes_es(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, calls)

        result = t.transcribe(np.zeros(16000, dtype=np.float32))

        assert calls["language"] == "es"
        assert result.duration == pytest.approx(1.0)

    def test_explicit_language_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, calls)
        monkeypatch.setattr(config, "LANGUAGE", "es")

        t.transcribe(np.zeros(16000, dtype=np.float32), language="de")

        assert calls["language"] == "de"


class TestTranscribeResult:
    def test_assembles_segments_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, calls)

        result = t.transcribe(np.zeros(16000, dtype=np.float32))

        assert [s.text for s in result.segments] == ["hola", "mundo"]
        assert [s.start for s in result.segments] == [0.0, 0.5]
        assert [s.end for s in result.segments] == [0.5, 1.0]
        assert result.model == t.model_name


class TestTranscribeErrors:
    def test_empty_audio_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, calls)

        with pytest.raises(TranscriberError):
            t.transcribe(np.array([], dtype=np.float32))

    def test_model_errors_are_wrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = Transcriber()
        t._model = types.SimpleNamespace(  # type: ignore[assignment]
            transcribe=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        monkeypatch.setattr(Transcriber, "_load_model", lambda self: None)

        with pytest.raises(TranscriberError):
            t.transcribe(np.zeros(1600, dtype=np.float32))
