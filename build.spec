# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build specification for Voz.

Produces dist/voz/voz.exe (--onedir mode).
The Whisper model is kept outside the .exe at models/whisper/
so the total build stays under ~200 MB.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# ── faster-whisper assets (VAD model, etc.) ─────────────────────────────────
fw_data = collect_data_files("faster_whisper")

# ── Main analysis ───────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=fw_data,
    hiddenimports=[
        # Core transcription
        "faster_whisper",
        "ctranslate2",
        "onnxruntime",
        "tokenizers",
        # Audio I/O (GUI-only)
        "sounddevice",
        # Signal processing
        "numpy",
        "scipy.signal",
        # GUI
        "pynput",
        "pyperclip",
        # Model download
        "huggingface_hub",
        "tqdm",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter.test",
        "pip",
        "idlelib",
        "turtle",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── Bytecode archive ────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Executable ──────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voz",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # Compress with UPX when available
    console=False,          # No console window in GUI-only mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── One-directory bundle ────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="voz",
)
