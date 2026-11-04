"""Busca dos PNGs do logo/ícone, rodando do fonte ou instalado via .deb."""

from __future__ import annotations

import glob
import os
import tkinter as tk
from functools import lru_cache
from tkinter import ttk

from .constants import LOGO_DIRS, SCRIPT_DIR


@lru_cache(maxsize=1)
def _list_logo_pngs() -> tuple[str, ...]:
    return tuple(_scan_logo_pngs())


def list_logo_pngs() -> list[str]:
    """Lista os PNGs do logo disponíveis (fonte ou instalado), menor -> maior."""
    return list(_list_logo_pngs())


def _scan_logo_pngs() -> list[str]:
    for d in LOGO_DIRS:
        found = sorted(
            glob.glob(os.path.join(d, "gravabin-*.png")),
            key=lambda p: int("".join(filter(str.isdigit, os.path.basename(p))) or 0),
        )
        if found:
            return found
    # Fallback: ícones instalados pelo pacote .deb
    hicolor = [
        f"/usr/share/icons/hicolor/{s}x{s}/apps/gravabin.png"
        for s in (16, 24, 32, 48, 64, 96, 128, 256)
    ]
    found = [p for p in hicolor if os.path.isfile(p)]
    if found:
        return found
    for p in ("/usr/share/pixmaps/gravabin.png",
              os.path.join(SCRIPT_DIR, "gravabin.png")):
        if os.path.isfile(p):
            return [p]
    return []


def find_logo_png(target: int) -> str | None:
    """PNG do logo mais próximo (>=) do tamanho pedido, senão o maior menor."""
    pngs = list_logo_pngs()
    if not pngs:
        return None

    def size_of(path: str) -> int:
        digits = "".join(filter(str.isdigit, os.path.basename(path)))
        return int(digits) if digits else 0

    for p in pngs:
        if size_of(p) >= target:
            return p
    return pngs[-1]


def _scale(img: tk.PhotoImage, target: int) -> tk.PhotoImage:
    """Tk só escala por fatores inteiros: aproxima target por zoom(a)/subsample(b)."""
    w = img.width()
    if w <= 0 or w == target:
        return img
    best = None
    for den in range(1, 17):
        num = max(1, round(target * den / w))
        err = abs(w * num / den - target)
        if best is None or err < best[0]:
            best = (err, num, den)
    _, num, den = best
    if num > 1:
        img = img.zoom(num, num)
    if den > 1:
        img = img.subsample(den, den)
    return img


def load_logo(master: tk.Misc, target: int = 88) -> "tk.PhotoImage | None":
    """Carrega o PNG do logo como tk.PhotoImage com ~target px, ou None."""
    path = find_logo_png(target)
    if not path:
        return None
    try:
        img = tk.PhotoImage(file=path, master=master)
    except tk.TclError:
        return None
    return _scale(img, target)


class LogoLabel(ttk.Frame):
    """Logo que ocupa o espaço livre da célula onde é colocado.

    O quadro pede 1x1 px, então o tamanho vem do grid (altura das linhas ao
    lado, largura restante) e cresce com a altura da janela (`window_frac`),
    empurrando a barra superior se precisar. A imagem é refeita, com
    debounce, conforme a célula muda — sem laço de realimentação, pois o
    label é posicionado com place() e não influencia o tamanho do quadro.
    """

    def __init__(self, parent: tk.Widget, min_size: int = 32,
                 max_size: int = 160, margin: int = 6,
                 window_frac: float = 0.15) -> None:
        super().__init__(parent, width=1, height=1)
        self._min, self._max, self._margin = min_size, max_size, margin
        self._frac = window_frac
        self._top = self.winfo_toplevel()
        self._top_bind = self._top.bind("<Configure>", self._on_top, add="+")
        self._cache: dict[int, tk.PhotoImage] = {}
        self._size = 0
        self._job: str | None = None
        self._label = ttk.Label(self)
        self._label.place(relx=0.5, rely=0.5, anchor="center")
        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>", self._on_destroy)

    def _on_configure(self, event: tk.Event) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(40, self._apply, event.width, event.height)

    def _on_top(self, event: tk.Event) -> None:
        if event.widget is not self._top:
            return
        want = max(self._min, min(self._max, int(event.height * self._frac)))
        want += 2 * self._margin
        if int(self.cget("height")) != want:
            self.configure(height=want)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        try:
            self._top.unbind("<Configure>", self._top_bind)
        except tk.TclError:
            pass

    def _apply(self, width: int, height: int) -> None:
        self._job = None
        size = min(width, height) - 2 * self._margin
        size = min(size, int(self._top.winfo_height() * self._frac))
        size = max(self._min, min(self._max, size))
        if size == self._size:
            return
        img = self._cache.get(size)
        if img is None:
            img = load_logo(self, size)
            if img is None:
                return
            self._cache[size] = img
        self._size = size
        self._label.configure(image=img)
