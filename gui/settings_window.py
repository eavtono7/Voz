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


class SettingsWindow(tk.Toplevel):
    """Modal settings dialog."""

    def __init__(
        self,
        parent: tk.Tk,
        on_save: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save

        self.title("Configuración – Voz")
        self.geometry("500x440")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Theme
        self._bg = "#1e1e1e"
        self._fg = "#e0e0e0"
        self._entry_bg = "#2d2d2d"
        self._accent = "#4ec9b0"
        self.configure(bg=self._bg)

        self._build_ui()
        self._load_values()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Centre on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Create all form controls."""
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TLabel", background=self._bg, foreground=self._fg)
        s.configure("TFrame", background=self._bg)
        s.configure(
            "TButton",
            background=self._accent, foreground="#1e1e1e",
            borderwidth=0, focuscolor="none",
        )
        s.map("TButton", background=[("active", "#3da890")])

        main = tk.Frame(self, bg=self._bg, padx=20, pady=20)
        main.pack(fill="both", expand=True)

        row = 0

        # Title
        tk.Label(
            main, text="⚙️  Configuración",
            font=("Segoe UI", 14, "bold"),
            bg=self._bg, fg=self._accent,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 15))
        row += 1

        # ── Micrófono ─────────────────────────────────────────────────
        self._lbl_mic = tk.Label(
            main, text="Micrófono:", bg=self._bg, fg=self._fg, anchor="w",
        )
        self._lbl_mic.grid(row=row, column=0, sticky="w", pady=5)

        self._mic_var = tk.StringVar()
        self._mic_combo = ttk.Combobox(
            main, textvariable=self._mic_var,
            width=42, state="readonly",
        )
        self._mic_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        self._populate_mics()
        row += 1

        # ── Idioma ────────────────────────────────────────────────────
        tk.Label(
            main, text="Idioma:", bg=self._bg, fg=self._fg, anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=5)

        self._lang_var = tk.StringVar()
        ttk.Combobox(
            main, textvariable=self._lang_var,
            values=["es", "en", "fr", "de", "pt", "it", "auto"],
            width=10, state="readonly",
        ).grid(row=row, column=1, sticky="w", pady=5, padx=(10, 0))
        row += 1

        # ── Modelo ────────────────────────────────────────────────────
        tk.Label(
            main, text="Modelo:", bg=self._bg, fg=self._fg, anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=5)

        self._model_var = tk.StringVar()
        ttk.Combobox(
            main, textvariable=self._model_var,
            values=["turbo", "large-v3", "medium", "small", "base", "tiny"],
            width=15, state="readonly",
        ).grid(row=row, column=1, sticky="w", pady=5, padx=(10, 0))
        row += 1

        # ── Tecla rápida ──────────────────────────────────────────────
        tk.Label(
            main, text="Tecla rápida:", bg=self._bg, fg=self._fg, anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=5)

        self._hotkey_var = tk.StringVar()
        tk.Entry(
            main, textvariable=self._hotkey_var,
            width=10, bg=self._entry_bg, fg=self._fg,
            insertbackground=self._fg,
            relief="flat", font=("Segoe UI", 10, "bold"), justify="center",
        ).grid(row=row, column=1, sticky="w", pady=5, padx=(10, 0))
        row += 1

        # ── Checkboxes ────────────────────────────────────────────────
        opt = tk.Frame(main, bg=self._bg)
        opt.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 5))
        row += 1

        self._auto_copy_var = tk.BooleanVar()
        tk.Checkbutton(
            opt, text="Copiar al portapapeles automáticamente",
            variable=self._auto_copy_var,
            bg=self._bg, fg=self._fg, selectcolor=self._entry_bg,
            activebackground=self._bg, activeforeground=self._fg,
        ).pack(anchor="w")

        self._auto_save_var = tk.BooleanVar()
        tk.Checkbutton(
            opt, text="Guardar transcripción automáticamente",
            variable=self._auto_save_var,
            bg=self._bg, fg=self._fg, selectcolor=self._entry_bg,
            activebackground=self._bg, activeforeground=self._fg,
        ).pack(anchor="w")

        # ── Buttons ───────────────────────────────────────────────────
        btn_frame = tk.Frame(main, bg=self._bg)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=(15, 0))
        row += 1

        for txt, cmd in [("Cancelar", self._cancel), ("Guardar", self._save)]:
            tk.Button(
                btn_frame, text=txt, command=cmd,
                bg="#3a3a3a", fg=self._fg,
                relief="flat", padx=20, pady=5, cursor="hand2",
                activebackground="#4a4a4a", activeforeground="#ffffff",
            ).pack(side="left", padx=5)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _populate_mics(self) -> None:
        """Detect input devices and populate the dropdown."""
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            items = [
                f"{i}: {d['name']}"
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            ]
            self._mic_combo["values"] = items

            if not items:
                return

            # Select current device
            cur = config.MICROPHONE_DEVICE
            if cur is not None:
                match = [x for x in items if x.startswith(f"{cur}:")]
                if match:
                    self._mic_combo.set(match[0])
                    return

            # Prefer non-MME device
            for x in items:
                if "MME" not in x:
                    self._mic_combo.set(x)
                    return
            self._mic_combo.set(items[0])
        except Exception as exc:
            logger.warning("Could not enumerate microphones: %s", exc)

    def _load_values(self) -> None:
        """Copy current config values into the form."""
        self._lang_var.set(config.LANGUAGE or "es")
        self._model_var.set(config.MODEL)
        self._hotkey_var.set(config.HOTKEY)
        self._auto_copy_var.set(config.AUTO_COPY)
        self._auto_save_var.set(config.AUTO_SAVE)

    def _device_from_combo(self) -> Optional[int]:
        """Parse device index from the combo-box selection."""
        val = self._mic_var.get()
        if val and ":" in val:
            try:
                return int(val.split(":", maxsplit=1)[0])
            except ValueError:
                return None
        return config.MICROPHONE_DEVICE

    # ── Actions ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Validate and persist configuration."""
        hotkey = self._hotkey_var.get().strip().upper()
        if not hotkey:
            from tkinter import messagebox
            messagebox.showerror("Error", "La tecla rápida no puede estar vacía")
            return

        config.MICROPHONE_DEVICE = self._device_from_combo()
        config.LANGUAGE = self._lang_var.get()
        config.MODEL = self._model_var.get()
        config.HOTKEY = hotkey
        config.AUTO_COPY = self._auto_copy_var.get()
        config.AUTO_SAVE = self._auto_save_var.get()
        if not config.save():
            from tkinter import messagebox
            messagebox.showerror("Error", "No se pudo guardar la configuración.")
            return

        if self._on_save:
            self._on_save()
        self.destroy()

    def _cancel(self) -> None:
        self.destroy()
