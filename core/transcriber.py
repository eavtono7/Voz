"""
Speech-to-text via faster-whisper.

Transcriber converts raw audio arrays into TranscriptionResult objects.
It never writes files and never touches the microphone.

Audio file loading is provided as a separate function (load_audio)
for use by the CLI pipeline.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from core.models import TranscriptionResult, Segment
from core.audio import resample as _resample_audio
from core import config

# Values that mean "let Whisper detect the language" instead of a
# specific ISO-639-1 code. "auto" comes from the settings dialog.
_AUTO_LANGUAGE_VALUES = frozenset({"auto", "auto-detectar", "autodetectar", ""})


def _normalize_language(lang: Optional[str]) -> Optional[str]:
    """Map auto-detection markers to None (faster-whisper's auto mode).

    'auto' is NOT a valid whisper language code: passing it straight
    through makes the Tokenizer raise ValueError.
    """
    if lang is None:
        return None
    stripped = lang.strip().lower()
    if not stripped or stripped in _AUTO_LANGUAGE_VALUES:
        return None
    return stripped

logger = logging.getLogger(__name__)


class TranscriberError(Exception):
    """Raised when model loading or transcription fails."""


class Transcriber:
    """Wraps faster-whisper for speech-to-text.

    The model is loaded lazily on the first call to transcribe(),
    so creating a Transcriber instance is cheap.

    Thread-safe: each call to transcribe() is independent.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> None:
        self.model_name = model_name or config.MODEL
        self.device = device or config.DEVICE
        self.compute_type = compute_type or config.COMPUTE_TYPE
        self._model = None
        self._model_lock = threading.Lock()

    def _load_model(self) -> None:
        """Download (if needed) and load the Whisper model.

        Thread-safe: uses a lock to prevent duplicate loading.
        Model files are cached in config.MODEL_DIR.
        """
        if self._model is not None:
            logger.debug("Model already loaded, skipping")
            return

        logger.debug("Acquiring model lock")
        with self._model_lock:
            if self._model is not None:
                logger.debug("Model loaded by another thread, skipping")
                return

            from faster_whisper import WhisperModel

            snapshot = self._cached_snapshot_path()
            if snapshot is None:
                logger.info("Model not cached locally — will download first")
            else:
                logger.info("Model cached locally — loading from disk")

            logger.info(
                "Loading model  name=%s  device=%s  compute=%s  cache=%s",
                self.model_name,
                self.device,
                self.compute_type,
                config.MODEL_DIR,
            )

            try:
                logger.debug("Creating WhisperModel instance")
                if snapshot is not None:
                    # Point at the local snapshot dir: zero network access,
                    # app works fully offline with the cached files.
                    model_root = str(snapshot)
                else:
                    model_root = self.model_name

                self._model = WhisperModel(
                    model_root,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(config.MODEL_DIR),
                )
                logger.info("Model loaded successfully")
            except Exception as exc:
                logger.exception("Failed to load model")
                raise TranscriberError(
                    f"Failed to load model '{self.model_name}': {exc}"
                ) from exc

    @property
    def is_model_loaded(self) -> bool:
        """Return True if the Whisper model is already loaded in memory."""
        return self._model is not None

    def preload(self) -> None:
        """Trigger model download + load (may block for minutes on first call).

        Safe to call from any thread; subsequent calls are no-ops.
        """
        self._load_model()

    def unload(self) -> None:
        """Free the loaded model from memory (~1.2 GB RAM reclaimed by GC)."""
        with self._model_lock:
            self._model = None

    def is_model_cached(self) -> bool:
        """Check if the model files are already downloaded on disk.

        Works with any model by scanning for huggingface cache directories
        or direct-download model files under MODEL_DIR — but only adopts a
        cached copy when it matches the configured model (see
        _expected_repo_id), never a different one.
        """
        return self._cached_snapshot_path() is not None

    @staticmethod
    def _expected_repo_id() -> Optional[str]:
        """Resolve config.MODEL (alias like 'turbo' or an HF repo id) → repo id."""
        name = (config.MODEL or "").strip()
        if not name:
            return None
        try:
            from faster_whisper.utils import _MODELS
        except Exception:
            return name
        return _MODELS.get(name.lower(), name)

    @staticmethod
    def _candidate_repo_id(cache_dir_name: str) -> str:
        """models--org--name → org/name (case preserved; lowercase on use)."""
        return cache_dir_name[len("models--"):].replace("--", "/")

    def _cached_snapshot_path(self) -> Optional[Path]:
        """Return the local snapshot dir containing model.bin, or None.

        Used to load the model straight from disk, bypassing Hugging Face
        network calls entirely (works offline, no metadata probes).
        Only returns a snapshot of the configured model.
        """
        model_dir = config.MODEL_DIR
        expected = self._expected_repo_id()
        if expected is None:
            return None
        expected_low = expected.lower()

        for candidate in model_dir.glob("models--*"):
            if not candidate.is_dir():
                continue
            if self._candidate_repo_id(candidate.name).lower() != expected_low:
                continue
            snaps = candidate / "snapshots"
            if snaps.exists():
                for snap_dir in snaps.iterdir():
                    if (snap_dir / "model.bin").is_file():
                        return snap_dir

        # Explicit local model directory injected directly under MODEL_DIR.
        if (model_dir / "model.bin").is_file():
            return model_dir
        return None

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio and return a rich result object.

        Args:
            audio: 1-D float32 numpy array at 16 kHz.
            language: Language code ('es', 'en', etc.) or None for auto-detect.

        Returns:
            TranscriptionResult with full text, segments, language, and metadata.

        Raises:
            TranscriberError if transcription fails.
        """
        logger.info("transcribe() called, audio samples: %d", len(audio))
        self._load_model()

        lang = _normalize_language(language or config.LANGUAGE or None)
        duration = len(audio) / config.SAMPLE_RATE

        logger.info(
            "Transcribing  duration=%.2fs  language=%s",
            duration,
            lang or "auto",
        )

        if len(audio) == 0:
            raise TranscriberError("Cannot transcribe empty audio")

        start = time.monotonic()

        try:
            logger.debug("Calling model.transcribe()")
            segments_gen, info = self._model.transcribe(
                audio,
                language=lang,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    threshold=0.5,
                ),
            )
            logger.debug("model.transcribe() returned")

            detected_language = info.language if info is not None else "unknown"
            segments: list[Segment] = []
            text_parts: list[str] = []

            logger.debug("Iterating over segments")
            for seg in segments_gen:
                text = seg.text.strip()
                logger.debug(
                    "Segment: start=%.2f end=%.2f chars=%d",
                    seg.start,
                    seg.end,
                    len(text),
                )
                segment = Segment(
                    start=round(seg.start, 2),
                    end=round(seg.end, 2),
                    text=text,
                )
                segments.append(segment)
                text_parts.append(text)

            full_text = " ".join(text_parts)
            elapsed = time.monotonic() - start

            logger.info(
                "Transcription complete  chars=%d  segments=%d  time=%.2fs",
                len(full_text),
                len(segments),
                elapsed,
            )

            return TranscriptionResult(
                text=full_text,
                language=detected_language,
                duration=duration,
                segments=segments,
                model=self.model_name,
            )

        except Exception as exc:
            logger.exception("Exception in transcribe()")
            raise TranscriberError(
                f"Transcription failed: {exc}"
            ) from exc


# ── Audio file loading ────────────────────────────────────────────────────────


def load_audio(path: Path, target_sr: int = 16_000) -> np.ndarray:
    """Load an audio file and return a 1-D float32 array at *target_sr* Hz.

    Supports: WAV, FLAC, OGG (via soundfile),
              MP3, M4A, AAC, etc. (via av / ffmpeg).

    Mono is produced by averaging channels.

    Raises:
        FileNotFoundError – path does not exist.
        ValueError – file cannot be decoded.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    # ── Try soundfile first (fast for WAV/FLAC/OGG) ──────────────────────
    try:
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != target_sr:
            audio = _resample(audio, sr, target_sr)
        return audio
    except Exception as exc:
        logger.debug("soundfile could not decode %s: %s", path.name, exc)

    # ── Fall back to av (handles MP3, M4A, AAC, …) ───────────────────────
    try:
        import av

        container = av.open(str(path))
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"No audio stream found in {path}")

        resampler = av.AudioResampler(
            format="fltp",
            layout="mono",
            rate=target_sr,
        )

        resampled_frames: list[av.AudioFrame] = []
        for frame in container.decode(audio=0):
            frame.pts = None
            for f in resampler.resample(frame):
                resampled_frames.append(f)

        if not resampled_frames:
            raise ValueError(f"No audio frames found in {path}")

        # Flush remaining frames from the resampler
        for f in resampler.resample(None):
            resampled_frames.append(f)

        audio = np.concatenate(
            [f.to_ndarray() for f in resampled_frames], axis=1
        )
        audio = audio[0].astype(np.float32)
        return audio

    except Exception as exc:
        raise ValueError(
            f"Cannot decode audio file '{path}': {exc}"
        ) from exc


def _resample(
    audio: np.ndarray, orig_sr: int, target_sr: int
) -> np.ndarray:
    """Resample audio to *target_sr* — delegates to core.audio.resample."""
    return _resample_audio(audio, orig_sr, target_sr)
