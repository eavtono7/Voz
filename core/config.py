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

# ── Paths (resolved at init()) ────────────────────────────────────────────────

BASE_DIR: Path  # Project root or directory containing voz.exe
MODEL_DIR: Path  # Where Whisper models are cached (outside .exe)
OUTPUT_DIR: Path  # Batch transcription output
DICTATIONS_DIR: Path  # Dictation session logs
CONFIG_PATH: Path  # Path to config.json
LOG_PATH: Path  # Path to voz.log


def init() -> None:
    """Resolve paths and load config.json from disk.

    Must be called once at startup, before any other module uses config values.
    Safe to call multiple times (idempotent after first call if paths don't change).
    """
    global BASE_DIR, MODEL_DIR, OUTPUT_DIR, DICTATIONS_DIR, CONFIG_PATH, LOG_PATH
    global MODEL, DEVICE, COMPUTE_TYPE, LANGUAGE, HOTKEY
    global AUTO_COPY, AUTO_SAVE, MICROPHONE_DEVICE

    # ── Detect environment ────────────────────────────────────────────────
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle: paths are relative to the .exe
        BASE_DIR = Path(sys.executable).parent.resolve()
    else:
        # Running as script:  core/config.py → up 2 levels → project root
        BASE_DIR = Path(__file__).resolve().parent.parent

    # ── Resolve all paths ─────────────────────────────────────────────────
    MODEL_DIR = BASE_DIR / "models" / "whisper"
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
            MODEL = data.get("model", MODEL)
            DEVICE = data.get("device", DEVICE)
            COMPUTE_TYPE = data.get("compute_type", COMPUTE_TYPE)
            LANGUAGE = data.get("language", LANGUAGE)
            HOTKEY = data.get("hotkey", HOTKEY)
            AUTO_COPY = data.get("auto_copy", AUTO_COPY)
            AUTO_SAVE = data.get("auto_save", AUTO_SAVE)
            MICROPHONE_DEVICE = data.get("microphone_device", MICROPHONE_DEVICE)
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
    """
    for key, value in kwargs.items():
        if key in globals():
            globals()[key] = value
            logger.debug("Config updated: %s = %r", key, value)
        else:
            logger.warning("Unknown config key: %s", key)
