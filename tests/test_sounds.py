"""
Tests for core.sounds — cues are optional, non-blocking and never raise.
"""

from __future__ import annotations

import threading

import pytest

import core.config as config
import core.sounds as sounds


def _capture(monkeypatch: pytest.MonkeyPatch) -> tuple[list, threading.Event]:
    played: list = []
    done = threading.Event()

    def fake_beep(tones) -> None:
        played.append(tones)
        done.set()

    monkeypatch.setattr(sounds, "_beep", fake_beep)
    return played, done


class TestPlay:
    @pytest.mark.parametrize("kind", ["start", "stop", "done", "error"])
    def test_known_cues_play(self, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
        monkeypatch.setattr(config, "SOUNDS", True)
        played, done = _capture(monkeypatch)

        sounds.play(kind)

        assert done.wait(2), "cue must be played on a background thread"
        assert played == [sounds._TONES[kind]]

    def test_disabled_by_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "SOUNDS", False)
        played, done = _capture(monkeypatch)

        sounds.play("start")

        assert not done.wait(0.2)
        assert played == []

    def test_unknown_cue_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "SOUNDS", True)
        played, done = _capture(monkeypatch)

        sounds.play("does-not-exist")

        assert not done.wait(0.2)
        assert played == []
