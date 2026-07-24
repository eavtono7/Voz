"""
Tests for core.models — dataclasses, serialization, defaults.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from core.models import Segment, TranscriptionResult


class TestSegment:
    def test_creation(self) -> None:
        seg = Segment(start=1.5, end=3.2, text="hola")
        assert seg.start == 1.5
        assert seg.end == 3.2
        assert seg.text == "hola"

    def test_empty_text(self) -> None:
        seg = Segment(start=0.0, end=1.0, text="")
        assert seg.text == ""


class TestTranscriptionResult:
    def test_creation_defaults(self) -> None:
        result = TranscriptionResult(
            text="hola mundo",
            language="es",
            duration=2.5,
            segments=[],
            model="turbo",
        )
        assert result.text == "hola mundo"
        assert result.language == "es"
        assert result.duration == 2.5
        assert result.segments == []
        assert result.model == "turbo"
        assert isinstance(result.created_at, datetime)

    def test_to_dict(self) -> None:
        result = TranscriptionResult(
            text="hola",
            language="es",
            duration=1.0,
            segments=[Segment(start=0.0, end=1.0, text="hola")],
            model="turbo",
        )
        d = result.to_dict()
        assert d["text"] == "hola"
        assert d["language"] == "es"
        assert d["duration"] == 1.0
        assert d["model"] == "turbo"
        assert isinstance(d["created_at"], str)
        assert len(d["segments"]) == 1
        assert d["segments"][0]["start"] == 0.0
        assert d["segments"][0]["end"] == 1.0
        assert d["segments"][0]["text"] == "hola"

    def test_to_json(self) -> None:
        result = TranscriptionResult(
            text="hola",
            language="es",
            duration=1.0,
            segments=[],
            model="turbo",
        )
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert parsed["text"] == "hola"
        assert parsed["language"] == "es"

    def test_to_dict_idempotent_with_json(self) -> None:
        """to_dict output must be JSON-serializable."""
        result = TranscriptionResult(
            text="test",
            language="en",
            duration=3.0,
            segments=[Segment(start=0.0, end=3.0, text="test")],
            model="tiny",
        )
        json.dumps(result.to_dict())

    def test_multiple_segments(self) -> None:
        result = TranscriptionResult(
            text="uno dos tres",
            language="es",
            duration=3.0,
            segments=[
                Segment(start=0.0, end=1.0, text="uno"),
                Segment(start=1.0, end=2.0, text="dos"),
                Segment(start=2.0, end=3.0, text="tres"),
            ],
            model="turbo",
        )
        assert len(result.segments) == 3
        assert result.to_dict()["segments"][1]["text"] == "dos"
