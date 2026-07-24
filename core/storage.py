"""
Persistence layer for transcription results.

Storage is the ONLY module in the project that writes files.
It produces human-readable .txt files and machine-readable .json files.

If you want to add Markdown, PDF, database, Notion, or any other output
format in the future, add it here – the rest of the codebase stays untouched.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

from core.models import TranscriptionResult
from core import config

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when a file operation fails."""


class Storage:
    """Saves TranscriptionResult objects to disk.

    Args:
        output_dir: Directory where files are written.
                    Defaults to config.DICTATIONS_DIR.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or config.DICTATIONS_DIR

    def save(
        self,
        result: TranscriptionResult,
        stem: str,
    ) -> Tuple[Path, Path]:
        """Persist a transcription result as .txt and .json.

        Args:
            result: The transcription to save.
            stem: Base filename (without extension), e.g. "dictado_20260708_183000".

        Returns:
            (txt_path, json_path) – the two files that were written.

        Raises:
            StorageError if either file cannot be written.
        """
        txt_path = self.output_dir / f"{stem}.txt"
        json_path = self.output_dir / f"{stem}.json"

        self._write_txt(result, txt_path)
        self._write_json(result, json_path)

        logger.info("Saved transcription: %s  %s", txt_path.name, json_path.name)
        return txt_path, json_path

    # ── Private helpers ───────────────────────────────────────────────────

    def _write_txt(self, result: TranscriptionResult, path: Path) -> None:
        """Write plain-text transcript."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(result.text, encoding="utf-8")
            logger.debug("Wrote TXT: %s (%d chars)", path.name, len(result.text))
        except OSError as exc:
            raise StorageError(f"Cannot write TXT {path}: {exc}") from exc

    def _write_json(self, result: TranscriptionResult, path: Path) -> None:
        """Write JSON with full metadata + segments."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                result.to_json(),
                encoding="utf-8",
            )
            logger.debug("Wrote JSON: %s", path.name)
        except OSError as exc:
            raise StorageError(f"Cannot write JSON {path}: {exc}") from exc
