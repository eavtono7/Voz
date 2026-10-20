"""
Central configuration for Voz.

All hardcoded values live here.  No other module in the project
contains hardcoded paths, model names, or magic numbers.

Usage:
    from core import config

    print(config.MODEL)           # "turbo"
    print(config.SAMPLE_RATE)     # 16000

At startup, call config.init() to resolve paths and load config.json.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
# These can be overridden via config.json at runtime.

MODEL: str = "turbo"
DEVICE: str = "cpu"
COMPUTE_TYPE: str = "int8"
LANGUAGE: str = "es"
SAMPLE_RATE: int = 16_000
CHANNELS: int = 1
HOTKEY: str = "F10"
AUTO_COPY: bool = True
AUTO_SAVE: bool = True
MICROPHONE_DEVICE: Optional[int] = None  # None = system default

# ── Whitelist of valid config keys ─────────────────────────────────────────────
_CONFIG_KEYS = {
    "MODEL", "DEVICE", "COMPUTE_TYPE", "LANGUAGE", "SAMPLE_RATE",
    "CHANNELS", "HOTKEY", "AUTO_COPY", "AUTO_SAVE", "MICROPHONE_DEVICE",
}

# Keys accepted by the global hotkey listener (pynput keyboard.Key names).
_HOTKEY_ALLOWED = frozenset(
    {f"f{n}" for n in range(1, 25)}
    | {
        "insert", "delete", "home", "end", "page_up", "page_down",
        "caps_lock", "num_lock", "scroll_lock", "pause", "print_screen",
        "media_play_pause", "media_stop", "media_previous", "media_next",
        "media_volume_up", "media_volume_down", "media_volume_mute",
    }
)

BASE_DIR: Path = Path(".")  # Project root or directory containing voz.exe
MODEL_DIR: Path = Path(".")  # Where Whisper models are cached (outside .exe)
OUTPUT_DIR: Path = Path(".")  # Batch transcription output
DICTATIONS_DIR: Path = Path(".")  # Dictation session logs
CONFIG_PATH: Path = Path(".")  # Path to config.json
LOG_PATH: Path = Path(".")  # Path to voz.log


def init() -> None:
    """Resolve paths and load config.json from disk.

    Must be called once at startup, before any other module uses config values.
    Safe to call multiple times (idempotent after first call if paths don't change).
    """
    global BASE_DIR, MODEL_DIR, OUTPUT_DIR, DICTATIONS_DIR, CONFIG_PATH, LOG_PATH
    global MODEL, DEVICE, COMPUTE_TYPE, LANGUAGE, HOTKEY
    global AUTO_COPY, AUTO_SAVE, MICROPHONE_DEVICE
    global SAMPLE_RATE, CHANNELS

    # ── Detect environment ────────────────────────────────────────────────
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle: paths are relative to the .exe
        BASE_DIR = Path(sys.executable).parent.resolve()
    else:
        # Running as script:  core/config.py → up 2 levels → project root
        BASE_DIR = Path(__file__).resolve().parent.parent

    # ── Resolve all paths ─────────────────────────────────────────────────
    if getattr(sys, "frozen", False):
        # exe mode: bundle dir is dist/voz → model next to the .exe
        MODEL_DIR = BASE_DIR / "models" / "whisper"
    else:
        # script mode: point at the SAME physical folder the exe uses
        # (dist/voz/models/whisper), so the model is downloaded exactly once
        # no matter which entry point is used. Keeps the app self-contained:
        # everything lives inside dist/voz.
        MODEL_DIR = BASE_DIR / "dist" / "voz" / "models" / "whisper"
    OUTPUT_DIR = BASE_DIR / "data" / "output"
    DICTATIONS_DIR = BASE_DIR / "data" / "dictations"
    CONFIG_PATH = BASE_DIR / "config.json"
    LOG_PATH = BASE_DIR / "data" / "voz.log"

    # ── Ensure directories exist ──────────────────────────────────────────
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DICTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # ── Load user config ──────────────────────────────────────────────────
    if CONFIG_PATH.exists():
        try:
            raw = CONFIG_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            MODEL = _validate_str(data.get("model"), "model", MODEL)
            DEVICE = _validate_str(data.get("device"), "device", DEVICE)
            COMPUTE_TYPE = _validate_str(data.get("compute_type"), "compute_type", COMPUTE_TYPE)
            LANGUAGE = _validate_language(data.get("language"), LANGUAGE)
            HOTKEY = _validate_hotkey(data.get("hotkey"), HOTKEY)
            AUTO_COPY = bool(data.get("auto_copy", AUTO_COPY))
            AUTO_SAVE = bool(data.get("auto_save", AUTO_SAVE))
            MICROPHONE_DEVICE = _validate_mic_device(
                data.get("microphone_device"), MICROPHONE_DEVICE
            )
            SAMPLE_RATE = _validate_positive_int(data.get("sample_rate"), "sample_rate", SAMPLE_RATE)
            CHANNELS = _validate_positive_int(data.get("channels"), "channels", CHANNELS)
            logger.info("Config loaded from %s", CONFIG_PATH)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load config (%s); using defaults", exc)
    else:
        logger.info("No config.json found; using defaults")


def save() -> bool:
    """Persist current configuration values to config.json.
    
    Returns True on success, False on failure (already logged).
    """
    data = {
        "model": MODEL,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "language": LANGUAGE,
        "hotkey": HOTKEY,
        "auto_copy": AUTO_COPY,
        "auto_save": AUTO_SAVE,
        "microphone_device": MICROPHONE_DEVICE,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
    }
    try:
        CONFIG_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Config saved to %s", CONFIG_PATH)
        return True
    except OSError as exc:
        logger.error("Failed to save config: %s", exc)
        return False


def update(**kwargs) -> None:
    """Update config values at runtime without touching disk.

    Call save() afterwards if you want to persist.
    Only keys in the _CONFIG_KEYS whitelist are accepted, and the value
    must type-check (no silent corruption from bad types at runtime).
    """
    for key, value in kwargs.items():
        if key not in _CONFIG_KEYS:
            logger.warning("Unknown config key (ignored): %s", key)
            continue
        if not _type_ok(key, value):
            logger.warning("Invalid type for config key %s (%r); ignored", key, value)
            continue
        globals()[key] = value
        logger.debug("Config updated: %s = %r", key, value)


def _type_ok(key: str, value: object) -> bool:
    """Simple runtime type guard for config.update()."""
    if key in ("MODEL", "DEVICE", "COMPUTE_TYPE", "LANGUAGE", "HOTKEY"):
        return isinstance(value, str) and bool(value.strip())
    if key in ("SAMPLE_RATE", "CHANNELS"):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if key in ("AUTO_COPY", "AUTO_SAVE"):
        return isinstance(value, bool)
    if key == "MICROPHONE_DEVICE":
        if isinstance(value, bool):  # bool is a subclass of int – reject
            return False
        return value is None or (isinstance(value, int) and value >= 0)
    return False


def _validate_str(value: object, name: str, default: str) -> str:
    """Return *value* if it is a non-empty string, otherwise *default*."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    logger.warning("Invalid config value for '%s' (%r), using default: %s", name, value, default)
    return default


def _validate_positive_int(value: object, name: str, default: int) -> int:
    """Return *value* if it is a positive integer, otherwise *default*."""
    if isinstance(value, int) and value > 0:
        return value
    logger.warning("Invalid config value for '%s' (%r), using default: %d", name, value, default)
    return default


def _validate_language(value: object, default: str) -> str:
    """Return *value* if it is a valid language marker, otherwise *default*.

    Accepts 'auto' (auto-detect) and 2-letter ISO-639-1 codes ('es', 'en'…).
    Longer codes (e.g. 3-letter) are rejected: faster-whisper only takes
    ISO-639-1 or None.
    """
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate == "auto":
            return candidate
        if len(candidate) == 2 and candidate.isalpha() and candidate.isascii():
            return candidate
    logger.warning("Invalid config value for 'language' (%r), using default: %r", value, default)
    return default


def _validate_hotkey(value: object, default: str) -> str:
    """Return *value* (uppercased) iff the key is bindable, else *default*.

    The GUI listener can only bind 'special' keys (pynput keyboard.Key
    attributes): F-keys, media keys, etc. A regular letter would make
    HotkeyListener.start() raise and the app would run with no hotkey.
    """
    if isinstance(value, str):
        candidate = value.strip().upper()
        if candidate and candidate.lower() in _HOTKEY_ALLOWED:
            return candidate
    logger.warning("Invalid config value for 'hotkey' (%r), using default: %r", value, default)
    return default


def _validate_mic_device(value: object, default: Optional[int]) -> Optional[int]:
    """Return *value* if it is a valid device index (int >= 0) or None."""
    if isinstance(value, bool):
        logger.warning("Invalid config value for 'microphone_device' (bool %r), using default: %r",
                       value, default)
        return default
    if value is None:
        return None
    if isinstance(value, int) and value >= 0:
        return value
    logger.warning("Invalid config value for 'microphone_device' (%r), using default: %r",
                   value, default)
    return default
