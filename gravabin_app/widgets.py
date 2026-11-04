"""Widgets compartilhados: configurações de gravação e tabela de presets."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from .constants import (
    BAUDS,
    CHIPS,
    DEFAULT_ROWS_DATA,
    DEFAULT_SETTINGS,
    FLASH_FREQS,
    FLASH_MODES,
    FLASH_SIZES,
)


class FlashSettings(ttk.Frame):
    """Chip, baud, modo/freq/tamanho da flash e opções de gravação."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        d = DEFAULT_SETTINGS

        def combo(label: str, values: list[str], row: int, col: int,
                  default: str) -> ttk.Combobox:
            ttk.Label(self, text=label).grid(row=row, column=col, sticky="e")
            cmb = ttk.Combobox(self, width=10, values=values, state="readonly")
            cmb.set(default)
            cmb.grid(row=row, column=col + 1, padx=4, pady=4, sticky="w")
            return cmb

        self._combos = {
            "chip": combo("Chip:", CHIPS, 0, 0, d["chip"]),
            "baud": combo("Baud:", BAUDS, 0, 2, d["baud"]),
            "flash_mode": combo("Flash mode:", FLASH_MODES, 1, 0,
                                d["flash_mode"]),
            "flash_freq": combo("Freq:", FLASH_FREQS, 1, 2, d["flash_freq"]),
            "flash_size": combo("Size:", FLASH_SIZES, 1, 4, d["flash_size"]),
        }
        self._checks = {
            "erase": tk.BooleanVar(value=d["erase"]),
            "compress": tk.BooleanVar(value=d["compress"]),
            "verify": tk.BooleanVar(value=d["verify"]),
        }
        ttk.Checkbutton(self, text="Apagar flash antes",
                        variable=self._checks["erase"]
                        ).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Checkbutton(self, text="Comprimir (-z)",
                        variable=self._checks["compress"]
                        ).grid(row=2, column=3, sticky="w")
        ttk.Checkbutton(self, text="Verificar após gravar",
                        variable=self._checks["verify"]
                        ).grid(row=2, column=4, columnspan=2, sticky="w")

    def get(self) -> dict:
        out: dict = {k: c.get() for k, c in self._combos.items()}
        out.update({k: v.get() for k, v in self._checks.items()})
        return out

    def set(self, settings: dict | None) -> None:
        """Aplica as chaves presentes e válidas; as demais ficam como estão."""
        for key, value in (settings or {}).items():
            if key in self._combos and value in self._combos[key]["values"]:
                self._combos[key].set(value)
            elif key in self._checks and isinstance(value, bool):
                self._checks[key].set(value)

    def set_state(self, enabled: bool) -> None:
        for w in self.winfo_children():
            if isinstance(w, ttk.Combobox):
                w.configure(state="readonly" if enabled else "disabled")
            elif isinstance(w, ttk.Checkbutton):
                w.state(["!disabled"] if enabled else ["disabled"])


class BinRow:
    def __init__(self, parent: tk.Widget, offset: str = "", path: str = "",
                 hint: str = "", use: bool = False) -> None:
        self.var_use = tk.BooleanVar(value=use)
        self.var_offset = tk.StringVar(value=offset)
        self.var_path = tk.StringVar(value=path)
        self.hint = hint

        self.chk = ttk.Checkbutton(parent, variable=self.var_use)
        self.ent_off = ttk.Entry(parent, textvariable=self.var_offset, width=10)
        self.ent_path = ttk.Entry(parent, textvariable=self.var_path, width=55)
        self.btn = ttk.Button(parent, text="…", width=3, command=self._browse)
        self.lbl = ttk.Label(parent, text=hint, foreground="#888")

    def grid(self, row: int) -> None:
        self.chk.grid(row=row, column=0, padx=2, pady=2)
        self.ent_off.grid(row=row, column=1, padx=2, pady=2)
        self.ent_path.grid(row=row, column=2, padx=2, pady=2, sticky="ew")
        self.btn.grid(row=row, column=3, padx=2, pady=2)
        self.lbl.grid(row=row, column=4, padx=4, sticky="w")

    def destroy(self) -> None:
        for w in (self.chk, self.ent_off, self.ent_path, self.btn, self.lbl):
            w.destroy()

    def _browse(self) -> None:
        fn = filedialog.askopenfilename(
            title="Selecione o binário",
            filetypes=[("Binários", "*.bin"), ("Todos", "*.*")],
        )
        if fn:
            self.var_path.set(fn)
            self.var_use.set(True)

    def is_active(self) -> bool:
        return self.var_use.get() and bool(self.var_path.get().strip())

    def values(self) -> tuple[str, str]:
        return self.var_offset.get().strip(), self.var_path.get().strip()

    def data(self) -> dict:
        return {
            "use": self.var_use.get(),
            "offset": self.var_offset.get().strip(),
            "path": self.var_path.get().strip(),
            "hint": self.hint,
        }


class PresetPanel(ttk.Frame):
    """Uma aba de preset: tabela de binários (offset + arquivo)."""

    def __init__(self, parent: tk.Widget, name: str,
                 rows_data: list[dict] | None = None,
                 is_default: bool = False,
                 settings: dict | None = None) -> None:
        super().__init__(parent, padding=8)
        self.name = name
        self.is_default = is_default
        # Configurações de gravação do preset (None em presets antigos).
        self.settings = settings

        self.table = ttk.Frame(self)
        self.table.pack(fill="x")
        self.table.columnconfigure(2, weight=1)

        for col, txt in enumerate(
                ("Usar", "Offset", "Arquivo .bin", "", "Sugestão")):
            ttk.Label(self.table, text=txt).grid(
                row=0, column=col, sticky="w" if col >= 2 else "")

        # A quantidade de linhas é fixa (uma por binário típico do ESP);
        # os valores salvos são sobrepostos por índice.
        saved = rows_data or []
        self.rows: list[BinRow] = []
        for i, base in enumerate(DEFAULT_ROWS_DATA):
            s = saved[i] if i < len(saved) else {}
            row = BinRow(self.table,
                         s.get("offset", base["offset"]),
                         s.get("path", ""),
                         base["hint"],
                         s.get("use", False))
            self.rows.append(row)
            row.grid(i + 1)

    def active_files(self) -> list[tuple[str, str]]:
        return [r.values() for r in self.rows if r.is_active()]

    def dump(self) -> dict:
        out = {"name": self.name, "rows": [r.data() for r in self.rows]}
        if self.settings:
            out["settings"] = self.settings
        return out
