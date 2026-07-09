"""
Microphone audio capture via sounddevice.

Recorder captures raw PCM audio from any input device and returns
it as a 1-D float32 numpy array at the configured sample rate.

This module never writes files and never touches Whisper.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from core import config

logger = logging.getLogger(__name__)


class RecorderError(Exception):
    """Raised when a recording operation fails."""


class Recorder:
    """Captures microphone audio using sounddevice.

    Usage:
        recorder = Recorder(device=None)   # None = system default
        recorder.start()
        # ... talk ...
        audio = recorder.stop()            # np.ndarray, shape=(samples,)

    Audio format:
        - Sample rate: 16 kHz (configurable)
        - Channels: mono (configurable)
        - Data type: float32, range [-1, 1]
    """

    def __init__(
        self,
        samplerate: int | None = None,
        channels: int | None = None,
        device: int | None = None,
        blocksize: int = 1024,
    ) -> None:
        self.target_samplerate = samplerate if samplerate is not None else config.SAMPLE_RATE
        self.channels = channels if channels is not None else config.CHANNELS
        self.device = device
        self.blocksize = blocksize

        # Detect native sample rate of the device
        self.samplerate = self._detect_samplerate()

        self._buffer: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self.is_recording: bool = False

    def _detect_samplerate(self) -> int:
        """Detect the native sample rate of the audio device."""
        try:
            device_info = sd.query_devices(self.device)
            native_sr = int(device_info['default_samplerate'])
            logger.info(
                "Detected device %s native sample rate: %d Hz",
                self.device or "default",
                native_sr,
            )
            return native_sr
        except Exception as exc:
            logger.warning(
                "Could not detect native sample rate for device %s: %s. Using target rate.",
                self.device,
                exc,
            )
            return self.target_samplerate

    def start(self) -> None:
        """Open the microphone stream and begin buffering audio.

        Raises RecorderError if the device cannot be opened.
        """
        if self.is_recording:
            logger.warning("Recorder is already recording; ignoring start()")
            return

        self._buffer.clear()
        self.is_recording = True

        try:
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                device=self.device,
                blocksize=self.blocksize,
                callback=self._callback,
                dtype="float32",
            )
            self._stream.start()
            logger.info(
                "Recording started  device=%s  rate=%s  channels=%s",
                self.device or "default",
                self.samplerate,
                self.channels,
            )
        except Exception as exc:
            self.is_recording = False
            self._buffer.clear()
            raise RecorderError(
                f"Failed to open microphone (device={self.device}): {exc}"
            ) from exc

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        """Called by sounddevice from the audio capture thread."""
        if status:
            logger.warning("Audio input status: %s", status)
        self._buffer.append(indata.copy())

    def stop(self) -> np.ndarray:
        """Close the stream and return captured audio.

        Returns:
            1-D float32 numpy array, shape (samples,).
            Empty array if nothing was captured.
        """
        if not self.is_recording:
            logger.warning("Recorder is not recording; ignoring stop()")
            return np.array([], dtype=np.float32)

        self.is_recording = False

        # Tear down the stream (stop + close, even on failure)
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:
                logger.error("Error while stopping audio stream: %s", exc)
            finally:
                try:
                    self._stream.close()
                except Exception as exc:
                    logger.error("Error while closing audio stream: %s", exc)
                self._stream = None

        # Concatenate all buffered chunks
        if not self._buffer:
            logger.warning("No audio data captured during recording")
            return np.array([], dtype=np.float32)

        audio = np.concatenate(self._buffer, axis=0)
        audio = audio.flatten()
        self._buffer.clear()

        # Resample if native rate differs from target rate
        if self.samplerate != self.target_samplerate:
            logger.info(
                "Resampling from %d Hz to %d Hz",
                self.samplerate,
                self.target_samplerate,
            )
            audio = self._resample(audio, self.samplerate, self.target_samplerate)

        duration = len(audio) / self.target_samplerate
        logger.info(
            "Recording stopped  samples=%d  duration=%.2fs",
            len(audio),
            duration,
        )
        return audio

    def _resample(self, audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Resample audio from orig_sr to target_sr using scipy."""
        from scipy import signal

        if orig_sr == target_sr:
            return audio

        # Calculate the number of samples in the resampled signal
        num_samples = int(len(audio) * target_sr / orig_sr)
        resampled = signal.resample(audio, num_samples)
        return resampled.astype(np.float32)

    @property
    def recording_duration(self) -> float:
        """Current duration of the ongoing recording, in seconds."""
        if not self._buffer:
            return 0.0
        total = sum(len(chunk) for chunk in self._buffer)
        return total / self.samplerate  # Use native rate during recording
