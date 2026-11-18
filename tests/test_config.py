"""
Tests for core.config — defaults, load/save, validation.
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
    "HOTKEY": "F10",
    "AUTO_COPY": True,
    "AUTO_PASTE": True,
    "AUTO_SAVE": True,
    "SOUNDS": True,
    "MICROPHONE_DEVICE": None,
    "MODEL_UNLOAD_MIN": 10,
    "BATCH_SIZE": 8,
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
        assert config.AUTO_COPY is True
        assert config.AUTO_PASTE is True
        assert config.AUTO_SAVE is True
        assert config.SOUNDS is True
        assert config.MICROPHONE_DEVICE is None
        assert config.BATCH_SIZE == 8

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
                    "auto_paste": False,
                    "sounds": False,
                    "microphone_device": 2,
                    "batch_size": 0,
                }
            ),
            encoding="utf-8",
        )
        config.init()
        assert config.MODEL == "large-v3"
        assert config.LANGUAGE == "en"
        assert config.HOTKEY == "F9"
        assert config.AUTO_COPY is False
        assert config.AUTO_PASTE is False
        assert config.SOUNDS is False
        assert config.MICROPHONE_DEVICE == 2
        assert config.BATCH_SIZE == 0

    def test_audio_format_is_not_configurable(
        self, isolated: None, tmp_path: Path
    ) -> None:
        """Whisper only accepts 16 kHz mono: old config files can't break it."""
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"sample_rate": 48000, "channels": 2}), encoding="utf-8"
        )
        config.init()
        assert config.SAMPLE_RATE == 16_000
        assert config.CHANNELS == 1

        config.save()
        raw = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert "sample_rate" not in raw
        assert "channels" not in raw

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

    def test_bogus_json_fallback(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        config.init()
        assert config.MODEL == "turbo"

    def test_language_auto_accepted(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"language": "AUTO"}), encoding="utf-8"
        )
        config.init()
        assert config.LANGUAGE == "auto"

    def test_language_3letter_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"language": "spa"}), encoding="utf-8"
        )
        config.init()
        assert config.LANGUAGE == "es"

    def test_microphone_device_string_rejected(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"microphone_device": "1"}), encoding="utf-8"
        )
        config.init()
        assert config.MICROPHONE_DEVICE is None

    def test_microphone_device_bool_rejected(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"microphone_device": True}), encoding="utf-8"
        )
        config.init()
        assert config.MICROPHONE_DEVICE is None

    def test_microphone_device_index_zero_valid(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"microphone_device": 0}), encoding="utf-8"
        )
        config.init()
        assert config.MICROPHONE_DEVICE == 0

    def test_hotkey_letter_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"hotkey": "K"}), encoding="utf-8"
        )
        config.init()
        assert config.HOTKEY == "F10"

    def test_hotkey_valid_normalized_upper(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"hotkey": "f9"}), encoding="utf-8"
        )
        config.init()
        assert config.HOTKEY == "F9"

    def test_hotkey_insert_accepted(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"hotkey": "insert"}), encoding="utf-8"
        )
        config.init()
        assert config.HOTKEY == "INSERT"


class TestModelUnloadMin:
    def test_default_is_10(self, isolated: None) -> None:
        config.init()
        assert config.MODEL_UNLOAD_MIN == 10

    def test_zero_disables_feature(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model_unload_min": 0}), encoding="utf-8"
        )
        config.init()
        assert config.MODEL_UNLOAD_MIN == 0

    def test_negative_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model_unload_min": -5}), encoding="utf-8"
        )
        config.init()
        assert config.MODEL_UNLOAD_MIN == 10

    def test_string_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model_unload_min": "30"}), encoding="utf-8"
        )
        config.init()
        assert config.MODEL_UNLOAD_MIN == 10

    def test_bool_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model_unload_min": True}), encoding="utf-8"
        )
        config.init()
        assert config.MODEL_UNLOAD_MIN == 10

    def test_beyond_one_day_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model_unload_min": 1441}), encoding="utf-8"
        )
        config.init()
        assert config.MODEL_UNLOAD_MIN == 10

    def test_valid_value_loaded_and_persisted(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"model_unload_min": 30}), encoding="utf-8"
        )
        config.init()
        assert config.MODEL_UNLOAD_MIN == 30
        config.MODEL_UNLOAD_MIN = 20
        config.save()
        raw = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert raw["model_unload_min"] == 20


class TestBatchSize:
    def test_negative_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"batch_size": -1}), encoding="utf-8"
        )
        config.init()
        assert config.BATCH_SIZE == 8

    def test_bool_rejected(self, isolated: None, tmp_path: Path) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"batch_size": True}), encoding="utf-8"
        )
        config.init()
        assert config.BATCH_SIZE == 8

    def test_valid_value_loaded_and_persisted(
        self, isolated: None, tmp_path: Path
    ) -> None:
        tmp_path.joinpath("config.json").write_text(
            json.dumps({"batch_size": 4}), encoding="utf-8"
        )
        config.init()
        assert config.BATCH_SIZE == 4
        config.save()
        raw = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert raw["batch_size"] == 4
