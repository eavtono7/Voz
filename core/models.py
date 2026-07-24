"""
Data models for transcription results.

TranscriptionResult y Segment son los únicos objetos que viajan
entre módulos. Ninguno tiene lógica de negocio ni efectos secundarios.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class Segment:
    """A single segment of transcribed audio with timestamps."""

    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    """Complete result of a transcription operation.

    This object is created by Transcriber and consumed by:
      - Clipboard (to copy text)
      - Storage   (to save files)
      - GUI       (to display)
      - CLI       (to print)

    It is intentionally rich: contains timestamps, language, duration
    and metadata so consumers can choose what they need.
    """

    text: str
    language: str
    duration: float
    segments: List[Segment]
    model: str
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "text": self.text,
            "language": self.language,
            "duration": self.duration,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in self.segments
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(
            self.to_dict(), indent=indent, ensure_ascii=False
        )
