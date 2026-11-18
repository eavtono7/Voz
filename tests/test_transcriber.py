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
    monkeypatch.setattr(config, "BATCH_SIZE", 0)  # classic path by default
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


class TestBatchedMode:
    """BATCH_SIZE > 1 routes through faster-whisper's batched pipeline."""

    def test_batch_size_uses_batched_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        classic: Dict[str, Any] = {}
        batched: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, classic)
        monkeypatch.setattr(config, "BATCH_SIZE", 8)

        class FakePipeline:
            def __init__(self, model: Any) -> None:
                batched["model"] = model

            def transcribe(self, audio: np.ndarray, **kwargs: Any):
                batched.update(kwargs)
                return (
                    iter([_FakeSegment(0.0, 1.0, "por lotes")]),
                    types.SimpleNamespace(language="es"),
                )

        monkeypatch.setattr("faster_whisper.BatchedInferencePipeline", FakePipeline)

        result = t.transcribe(np.zeros(16000, dtype=np.float32))

        assert result.text == "por lotes"
        assert batched["model"] is t._model
        assert batched["batch_size"] == 8
        # Regression: the batched default drops punctuation and capitals.
        assert batched["without_timestamps"] is False
        assert batched["language"] == "es"
        assert batched["vad_filter"] is True
        assert classic == {}, "classic transcribe must not run in batched mode"

    def test_batch_size_zero_uses_classic_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: Dict[str, Any] = {}
        t = _make_faked_instance(monkeypatch, calls)

        result = t.transcribe(np.zeros(16000, dtype=np.float32))

        assert result.text == "hola mundo"
        assert "batch_size" not in calls


class TestCpuThreads:
    @pytest.mark.parametrize(
        "logical,expected", [(None, 4), (2, 4), (8, 4), (12, 6), (16, 8), (32, 8)]
    )
    def test_one_thread_per_physical_core_between_4_and_8(
        self, monkeypatch: pytest.MonkeyPatch, logical: Any, expected: int
    ) -> None:
        from core import transcriber

        monkeypatch.setattr(transcriber.os, "cpu_count", lambda: logical)
        assert transcriber._cpu_threads() == expected


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
        monkeypatch.setattr(config, "BATCH_SIZE", 0)

        with pytest.raises(TranscriberError):
            t.transcribe(np.zeros(1600, dtype=np.float32))


class _FakeWhisperModel:
    """Records the model_root passed to WhisperModel."""

    last_root: Any = None

    def __init__(self, model_size_or_path: str, **kwargs: Any) -> None:
        _FakeWhisperModel.last_root = model_size_or_path


class TestLocalSnapshotLoading:
    """Regression: cached models must load from disk, never via HF network.

    The cache guard must also match repo id: a cached model is only used
    when it is the one currently configured.
    """

    def _fake_cache(self, tmp_path: Any) -> Any:
        snapshot = tmp_path / "models--fake--model" / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "model.bin").write_bytes(b"x")
        return snapshot

    def test_cached_snapshot_path_found(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot = self._fake_cache(tmp_path)
        monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
        monkeypatch.setattr(
            Transcriber, "_expected_repo_id", staticmethod(lambda: "fake/model")
        )

        t = Transcriber()
        assert t._cached_snapshot_path() == snapshot

    def test_cached_flat_model_bin(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "model.bin").write_bytes(b"x")
        monkeypatch.setattr(config, "MODEL_DIR", tmp_path)

        t = Transcriber()
        assert t._cached_snapshot_path() == tmp_path

    def test_no_cache_returns_none(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
        monkeypatch.setattr(
            Transcriber, "_expected_repo_id", staticmethod(lambda: "fake/model")
        )
        assert Transcriber()._cached_snapshot_path() is None

    def test_mismatched_cached_model_not_adopted(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cached model for a DIFFERENT repo id must never be loaded."""
        self._fake_cache(tmp_path)
        monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
        monkeypatch.setattr(
            Transcriber, "_expected_repo_id", staticmethod(lambda: "other/model")
        )
        assert Transcriber()._cached_snapshot_path() is None

    def test_load_uses_local_path_when_cached(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Offline-safe: the snapshot dir is passed instead of the repo id."""
        snapshot = self._fake_cache(tmp_path)
        monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
        monkeypatch.setattr(
            Transcriber, "_expected_repo_id", staticmethod(lambda: "fake/model")
        )
        monkeypatch.setattr("faster_whisper.WhisperModel", _FakeWhisperModel)

        t = Transcriber()
        t._load_model()

        assert _FakeWhisperModel.last_root == str(snapshot)
        assert t.is_model_loaded

    def test_load_uses_repo_name_when_not_cached(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
        monkeypatch.setattr("faster_whisper.WhisperModel", _FakeWhisperModel)

        t = Transcriber()
        t._load_model()

        assert _FakeWhisperModel.last_root == t.model_name

    def test_expected_repo_id_resolves_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "MODEL", "turbo")
        repo = Transcriber._expected_repo_id()
        assert repo is not None and "turbo" in repo

    def test_expected_repo_id_passthrough_repo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "MODEL", "org/other-model")
        assert Transcriber._expected_repo_id() == "org/other-model"
