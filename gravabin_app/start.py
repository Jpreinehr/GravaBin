"""Tela inicial: escolha entre gravação única e gravação múltipla."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .constants import APP_NAME, APP_VERSION
from .logo import load_logo


class StartScreen:
    def __init__(self, root: tk.Tk, on_single, on_multi, on_compiler) -> None:
        self.root = root
        root.title(f"{APP_NAME} - Gravador ESP {APP_VERSION}")

        self.frame = ttk.Frame(root, padding=30)
        self.frame.pack(fill="both", expand=True)

        inner = ttk.Frame(self.frame)
        inner.place(relx=0.5, rely=0.45, anchor="center")

        self._logo_img = load_logo(root, target=128)
        if self._logo_img is not None:
            ttk.Label(inner, image=self._logo_img).pack(pady=(0, 8))
        ttk.Label(inner, text=APP_NAME, font=("TkDefaultFont", 22, "bold")
                  ).pack()
        ttk.Label(inner, text=f"Gravador ESP8266/ESP32 — versão {APP_VERSION}",
                  foreground="#666").pack(pady=(0, 24))

        style = ttk.Style()
        style.configure("Mode.TButton", font=("TkDefaultFont", 13, "bold"),
                        padding=(24, 14))

        cards = ttk.Frame(inner)
        cards.pack()
        self._card(cards, "Gravação única",
                   on_single).grid(row=0, column=0, padx=12)
        self._card(cards, "Gravação múltipla",
                   on_multi).grid(row=0, column=1, padx=12)
        self._card(cards, "Compilador",
                   on_compiler).grid(row=0, column=2, padx=12)

    def _card(self, parent: tk.Widget, title: str, command) -> ttk.Frame:
        card = ttk.Frame(parent, padding=10, relief="groove")
        ttk.Button(card, text=title, style="Mode.TButton",
                   command=command).pack(fill="x")
        return card

    def close(self) -> bool:
        self.frame.destroy()
        return True
