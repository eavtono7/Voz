"""
Tests for core.config — defaults, load/save, update whitelist, validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.config as config

_DEFAULTS = {
    "MODEL": "turbo",
    "DEVICE": "cpu",
    "COMPUTE_TYPE": "int8",
    "LANGUAGE": "es",
    "SAMPLE_RATE": 16_000,
    "CHANNELS": 1,
    "HOTKEY": "F10",
    "AUTO_COPY": True,
    "AUTO_SAVE": True,
    "MICROPHONE_DEVICE": None,
}


def _reset_to_defaults() -> None:
    for key, value in _DEFAULTS.items():
        setattr(config, key, value)


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch) -> None:
    """Make config.init() resolve all paths inside tmp_path."""
    _reset_to_defaults()

    # Trick config.init() into resolving BASE_DIR to tmp_path:
    #   Path(__file__).resolve().parent.parent  →  tmp_path
    monkeypatch.setattr(config, "__file__", str(tmp_path / "core" / "config.py"))


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_defaults_after_init(self, isolated: None) -> None:
        config.init()
        assert config.MODEL == "turbo"
        assert config.LANGUAGE == "es"
        assert config.HOTKEY == "F10"
        assert config.SAMPLE_RATE == 16_000
        assert config.CHANNELS == 1
        assert config.AUTO_COPY is True
        assert config.AUTO_SAVE is True
        assert config.MICROPHONE_DEVICE is None

    def test_paths_are_set_after_init(self, isolated: None) -> None:
        config.init()
        assert isinstance(config.BASE_DIR, Path)
        assert isinstance(config.CONFIG_PATH, Path)
        assert config.MODEL_DIR.exists()
        assert config.DICTATIONS_DIR.exists()


class TestLoadSave:
    def test_load_from_json(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps(
                {
                    "model": "large-v3",
                    "language": "en",
                    "hotkey": "F9",
                    "auto_copy": False,
                    "microphone_device": 2,
                    "sample_rate": 48000,
                    "channels": 2,
                }
            ),
            encoding="utf-8",
        )
        config.init()
        assert config.MODEL == "large-v3"
        assert config.LANGUAGE == "en"
        assert config.HOTKEY == "F9"
        assert config.AUTO_COPY is False
        assert config.MICROPHONE_DEVICE == 2
        assert config.SAMPLE_RATE == 48000
        assert config.CHANNELS == 2

    def test_save_persists_values(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model": "turbo", "language": "es", "hotkey": "F10"}),
            encoding="utf-8",
        )
        config.init()
        config.MODEL = "tiny"
        config.LANGUAGE = "fr"
        config.HOTKEY = "F11"

        assert config.save() is True
        assert config.CONFIG_PATH.exists()

        raw = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert raw["model"] == "tiny"
        assert raw["language"] == "fr"
        assert raw["hotkey"] == "F11"

    def test_save_and_reload_is_idempotent(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model": "turbo", "language": "es", "hotkey": "F10"}),
            encoding="utf-8",
        )
        config.init()
        config.MODEL = "base"
        config.save()

        _reset_to_defaults()
        config.CONFIG_PATH = tmp_path / "config.json"
        config.init()
        assert config.MODEL == "base"


class TestUpdateWhitelist:
    def test_update_accepts_known_keys(self, isolated: None) -> None:
        config.init()
        config.update(MODEL="small", LANGUAGE="de")
        assert config.MODEL == "small"
        assert config.LANGUAGE == "de"

    def test_update_ignores_unknown_keys(self, isolated: None) -> None:
        config.init()
        config.update(INVALID_KEY="should_be_ignored", NOT_CONFIG="x")
        assert not hasattr(config, "INVALID_KEY")

    def test_update_ignores_internal_names(self, isolated: None) -> None:
        config.init()
        config.update(BASE_DIR="/tmp/hack", init=lambda: None, logger="owned")
        assert config.BASE_DIR != "/tmp/hack"
        assert callable(config.init)


class TestValidation:
    def test_invalid_string_fields_fallback(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model": "", "hotkey": "   ", "language": "es"}),
            encoding="utf-8",
        )
        config.init()
        assert config.MODEL == "turbo"
        assert config.HOTKEY == "F10"

    def test_invalid_sample_rate_fallback(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps(
                {
                    "model": "turbo",
                    "language": "es",
                    "hotkey": "F10",
                    "sample_rate": -1,
                    "channels": 0,
                }
            ),
            encoding="utf-8",
        )
        config.init()
        assert config.SAMPLE_RATE == 16_000
        assert config.CHANNELS == 1

    def test_bogus_json_fallback(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        config.init()
        assert config.MODEL == "turbo"
