"""
Configuration dialog for Voz.

Persists changes to config.json and notifies the main app
via the *on_save* callback.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from core import config

logger = logging.getLogger(__name__)

LANG_LABELS = {
    "es": "Español",
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
    "auto": "Auto-detectar",
}


class SettingsWindow(tk.Toplevel):
    """Modal settings dialog."""

    def __init__(
        self,
        parent: tk.Tk,
        on_save: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save

        self.title("Configuración")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._bg = "#1e1e1e"
        self._fg = "#e0e0e0"
        self._entry_bg = "#2d2d2d"
        self._accent = "#4ec9b0"
        self._dim = "#808080"
        self._sep = "#3a3a3a"
        self.configure(bg=self._bg)

        self._mic_devices: list[tuple[int, str]] = []  # [(index, name), ...]
        self._mic_var = tk.StringVar()
        self._lang_var = tk.StringVar()
        self._model_var = tk.StringVar()
        self._hotkey_var = tk.StringVar()
        self._auto_copy_var = tk.BooleanVar()
        self._auto_save_var = tk.BooleanVar()

        self._build_ui()
        self._load_values()

        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _: self._cancel())
        self.bind("<Return>", lambda _: self._save())

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TLabel", background=self._bg, foreground=self._fg)
        s.configure("TFrame", background=self._bg)

        main = tk.Frame(self, bg=self._bg)
        main.pack(fill="both", expand=True, padx=24, pady=(24, 16))

        # Title
        tk.Label(
            main,
            text="Configuración",
            font=("Segoe UI", 16, "bold"),
            bg=self._bg,
            fg=self._accent,
            anchor="w",
        ).pack(fill="x", pady=(0, 16))

        # ── Audio section ──────────────────────────────────────────────
        self._section_header(main, "Audio")
        self._section_hint(main, "Selecciona el micrófono que usarás para dictar.")

        mic_frame = tk.Frame(main, bg=self._bg)
        mic_frame.pack(fill="x", pady=(6, 16))

        self._mic_combo = ttk.Combobox(
            mic_frame,
            textvariable=self._mic_var,
            state="readonly",
            font=("Segoe UI", 10),
        )
        self._mic_combo.pack(fill="x")
        self._populate_mics()

        # ── Transcripción section ──────────────────────────────────────
        self._section_header(main, "Transcripción")
        self._section_hint(
            main,
            'Modelos más grandes = mejor precisión pero más lentos.\n'
            '"turbo" es el equilibrio recomendado.',
        )

        row = tk.Frame(main, bg=self._bg)
        row.pack(fill="x", pady=(6, 4))

        tk.Label(
            row, text="Idioma", bg=self._bg, fg=self._fg,
            font=("Segoe UI", 10),
        ).pack(side="left")

        ttk.Combobox(
            row,
            textvariable=self._lang_var,
            values=list(LANG_LABELS.keys()),
            width=14,
            state="readonly",
            font=("Segoe UI", 10),
        ).pack(side="right")

        row2 = tk.Frame(main, bg=self._bg)
        row2.pack(fill="x", pady=(4, 16))

        tk.Label(
            row2, text="Modelo", bg=self._bg, fg=self._fg,
            font=("Segoe UI", 10),
        ).pack(side="left")

        ttk.Combobox(
            row2,
            textvariable=self._model_var,
            values=["turbo", "large-v3", "medium", "small", "base", "tiny"],
            width=14,
            state="readonly",
            font=("Segoe UI", 10),
        ).pack(side="right")

        # ── Hotkey section ─────────────────────────────────────────────
        self._section_header(main, "Atajo de teclado")
        self._section_hint(main, "Tecla global para iniciar/detener grabación.")

        hk_frame = tk.Frame(main, bg=self._bg)
        hk_frame.pack(fill="x", pady=(6, 16))

        self._hotkey_entry = tk.Entry(
            hk_frame,
            textvariable=self._hotkey_var,
            width=10,
            bg=self._entry_bg,
            fg=self._fg,
            insertbackground=self._fg,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
            justify="center",
        )
        self._hotkey_entry.pack()

        # ── Automation section ─────────────────────────────────────────
        self._section_header(main, "Automatización")

        opt = tk.Frame(main, bg=self._bg)
        opt.pack(fill="x", pady=(6, 10))

        tk.Checkbutton(
            opt,
            text="Copiar al portapapeles al terminar",
            variable=self._auto_copy_var,
            bg=self._bg,
            fg=self._fg,
            selectcolor=self._entry_bg,
            activebackground=self._bg,
            activeforeground=self._fg,
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        tk.Checkbutton(
            opt,
            text="Guardar transcripción en archivo",
            variable=self._auto_save_var,
            bg=self._bg,
            fg=self._fg,
            selectcolor=self._entry_bg,
            activebackground=self._bg,
            activeforeground=self._fg,
            font=("Segoe UI", 10),
        ).pack(anchor="w")

        # ── Buttons ────────────────────────────────────────────────────
        btn_frame = tk.Frame(main, bg=self._bg)
        btn_frame.pack(fill="x", pady=(8, 0))

        tk.Button(
            btn_frame,
            text="Cancelar",
            command=self._cancel,
            bg="#3a3a3a",
            fg=self._fg,
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Segoe UI", 10),
            activebackground="#4a4a4a",
            activeforeground="#ffffff",
        ).pack(side="left")

        tk.Button(
            btn_frame,
            text="Guardar cambios",
            command=self._save,
            bg=self._accent,
            fg="#1e1e1e",
            relief="flat",
            padx=24,
            pady=6,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            activebackground="#3da890",
        ).pack(side="right")

    def _section_header(self, parent: tk.Frame, text: str) -> None:
        sep = tk.Frame(parent, bg=self._sep, height=1)
        sep.pack(fill="x", pady=(8, 6))

        tk.Label(
            parent,
            text=text,
            bg=self._bg,
            fg=self._accent,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x")

    def _section_hint(self, parent: tk.Frame, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=self._bg,
            fg=self._dim,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        ).pack(fill="x")

    # ── Mic population ─────────────────────────────────────────────────────

    _NON_MIC_KEYWORDS = [
        "stereo mix", "loopback", "monitor", "wave out",
        "salida", "output", "altavoz", "speaker",
    ]

    def _populate_mics(self) -> None:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            self._mic_devices.clear()
            seen: set[str] = set()

            for i, d in enumerate(devices):
                if d["max_input_channels"] <= 0:
                    continue
                name = d["name"]
                name_lower = name.lower()
                if any(kw in name_lower for kw in self._NON_MIC_KEYWORDS):
                    continue
                if name in seen:
                    continue
                seen.add(name)
                self._mic_devices.append((i, name))

            names = [n for _, n in self._mic_devices]

            self._mic_combo["values"] = names

            if not names:
                return

            cur = config.MICROPHONE_DEVICE
            if cur is not None:
                for idx, name in self._mic_devices:
                    if idx == cur:
                        self._mic_combo.set(name)
                        return

            self._mic_combo.set(names[0])
        except Exception as exc:
            logger.warning("Could not enumerate microphones: %s", exc)

    # ── Load / Save ────────────────────────────────────────────────────────

    def _load_values(self) -> None:
        self._lang_var.set(config.LANGUAGE or "es")
        self._model_var.set(config.MODEL)
        self._hotkey_var.set(config.HOTKEY)
        self._auto_copy_var.set(config.AUTO_COPY)
        self._auto_save_var.set(config.AUTO_SAVE)

    def _selected_mic_index(self) -> Optional[int]:
        name = self._mic_var.get()
        for idx, dev_name in self._mic_devices:
            if dev_name == name:
                return idx
        return config.MICROPHONE_DEVICE

    def _save(self) -> None:
        hotkey = self._hotkey_var.get().strip().upper()
        if not hotkey:
            from tkinter import messagebox

            messagebox.showerror(
                "Error", "La tecla rápida no puede estar vacía.", parent=self
            )
            self._hotkey_entry.focus_set()
            return

        config.MICROPHONE_DEVICE = self._selected_mic_index()
        config.LANGUAGE = self._lang_var.get()
        config.MODEL = self._model_var.get()
        config.HOTKEY = hotkey
        config.AUTO_COPY = self._auto_copy_var.get()
        config.AUTO_SAVE = self._auto_save_var.get()

        if not config.save():
            from tkinter import messagebox

            messagebox.showerror(
                "Error", "No se pudo guardar la configuración.", parent=self
            )
            return

        logger.info("Settings saved — hotkey=%s mic=%s lang=%s model=%s",
                     hotkey, config.MICROPHONE_DEVICE, config.LANGUAGE, config.MODEL)

        if self._on_save:
            self._on_save()
        self.destroy()

    def _cancel(self) -> None:
        self.destroy()
