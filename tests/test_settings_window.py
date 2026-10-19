"""
Tests for gui.settings_window — save-time hotkey validation, mic selection.

Uses ONE shared Tk root per module: this Python/Tcl build misbehaves when
new Tk interpreters are created repeatedly in a single process, so each
test only creates and destroys a Toplevel on top of the shared root.
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.messagebox
import tkinter.ttk  # noqa: F401  (SettingsWindow uses ttk widgets)
from pathlib import Path

import pytest

import core.config as config
from gui.settings_window import SettingsWindow


@pytest.fixture(autouse=True)
def _quiet_logging() -> None:
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    yield root
    root.destroy()


class TestSaveValidation:
    def test_unsupported_hotkey_is_rejected_before_persisting(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tk_root
    ) -> None:
        cfg = tmp_path / "config.json"
        monkeypatch.setattr(config, "CONFIG_PATH", cfg)
        monkeypatch.setattr(config, "HOTKEY", "F10")

        errors: list[str] = []
        monkeypatch.setattr(
            tk.messagebox,
            "showerror",
            lambda *a, **k: errors.append(str(a)),
        )

        win = SettingsWindow(tk_root)
        try:
            win._hotkey_var.set("K")  # not a bindable key
            win._save()

            assert errors, "showerror must fire for an unsupported hotkey"
            assert win.winfo_exists(), "dialog must stay open on rejection"
            assert not cfg.exists(), "config.json must not be written"
            assert config.HOTKEY == "F10"
        finally:
            win.destroy()

    def test_supported_hotkey_persists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tk_root
    ) -> None:
        cfg = tmp_path / "config.json"
        monkeypatch.setattr(config, "CONFIG_PATH", cfg)
        monkeypatch.setattr(config, "MICROPHONE_DEVICE", None)

        win = SettingsWindow(tk_root)
        try:
            win._hotkey_var.set("F9")
            win._save()  # mutates config globals + writes cfg

            assert config.HOTKEY == "F9"
            assert cfg.exists()
            assert not win.winfo_exists(), "dialog must close after save"
        finally:
            if win.winfo_exists():
                win.destroy()


class TestMicSelection:
    def test_system_default_option_is_first_and_maps_to_none(
        self, monkeypatch: pytest.MonkeyPatch, tk_root
    ) -> None:
        monkeypatch.setattr(config, "MICROPHONE_DEVICE", None)

        win = SettingsWindow(tk_root)
        try:
            values = win._mic_combo["values"]
            assert values, "mic combobox must not be empty"
            win._mic_var.set(values[0])
            assert win._selected_mic_index() is None
        finally:
            win.destroy()

    def test_mic_devices_keep_unique_labels_when_names_collide(
        self, monkeypatch: pytest.MonkeyPatch, tk_root
    ):
        pytest.importorskip("sounddevice")
        import sounddevice as sd

        fake = [
            {"name": "Same Mic", "max_input_channels": 2, "hostapi": "WASAPI"},
            {"name": "Same Mic", "max_input_channels": 2, "hostapi": "MME"},
            {"name": "Stereo Mix", "max_input_channels": 2, "hostapi": "MME"},
            {"name": "Speakers", "max_input_channels": 0, "hostapi": "WASAPI"},
        ]
        monkeypatch.setattr(sd, "query_devices", lambda: fake)
        monkeypatch.setattr(config, "MICROPHONE_DEVICE", None)

        win = SettingsWindow(tk_root)
        try:
            values = list(win._mic_combo["values"])
            assert len(values) == 3  # system default + 2 distinct Same Mic
            assert len(set(values)) == len(values), "labels must be unique"
            assert not any("Stereo Mix" in v for v in values)
        finally:
            win.destroy()
