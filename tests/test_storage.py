"""
Tests for core.storage — file persistence, TXT + JSON output.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.models import Segment, TranscriptionResult
from core.storage import Storage, StorageError


@pytest.fixture
def sample_result() -> TranscriptionResult:
    return TranscriptionResult(
        text="hola mundo",
        language="es",
        duration=1.5,
        segments=[
            Segment(start=0.0, end=0.8, text="hola"),
            Segment(start=0.8, end=1.5, text="mundo"),
        ],
        model="turbo",
    )


@pytest.fixture
def storage() -> Storage:
    with tempfile.TemporaryDirectory() as tmp:
        yield Storage(output_dir=Path(tmp))


class TestStorage:
    def test_save_creates_both_files(
        self, storage: Storage, sample_result: TranscriptionResult
    ) -> None:
        txt_path, json_path = storage.save(sample_result, "test")
        assert txt_path.exists()
        assert json_path.exists()
        assert txt_path.suffix == ".txt"
        assert json_path.suffix == ".json"

    def test_txt_content(
        self, storage: Storage, sample_result: TranscriptionResult
    ) -> None:
        txt_path, _ = storage.save(sample_result, "test")
        content = txt_path.read_text(encoding="utf-8")
        assert content == "hola mundo"

    def test_json_content_matches_to_dict(
        self, storage: Storage, sample_result: TranscriptionResult
    ) -> None:
        _, json_path = storage.save(sample_result, "test")
        content = json_path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert parsed["text"] == sample_result.text
        assert parsed["language"] == sample_result.language
        assert parsed["duration"] == sample_result.duration
        assert parsed["model"] == sample_result.model
        assert len(parsed["segments"]) == 2
        assert isinstance(parsed["created_at"], str)

    def test_save_empty_text(
        self, storage: Storage, sample_result: TranscriptionResult
    ) -> None:
        sample_result.text = ""
        txt_path, _ = storage.save(sample_result, "empty")
        assert txt_path.read_text(encoding="utf-8") == ""

    def test_auto_creates_output_dir(self, sample_result: TranscriptionResult) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "sub" / "nested"
            storage = Storage(output_dir=nested)
            assert not nested.exists()

            txt_path, json_path = storage.save(sample_result, "deep")
            assert nested.exists()
            assert txt_path.exists()
            assert json_path.exists()

    def test_save_invalid_path_raises(self, sample_result: TranscriptionResult) -> None:
        storage = Storage(output_dir=Path("Z:/invalid_path_xyz/"))
        with pytest.raises(StorageError):
            storage.save(sample_result, "fail")
