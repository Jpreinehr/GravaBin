"""Ponto de entrada: cria a janela raiz e alterna entre as telas."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from .app import GravaBinApp
from .compiler import CompilerScreen
from .logo import list_logo_pngs
from .multi import MultiFlashScreen
from .start import StartScreen


class Shell:
    """Mantém uma tela por vez na janela: inicial, única, múltipla ou compilador."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.screen = None
        root.geometry("1000x780")
        root.minsize(820, 600)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_start()

    def _replace(self, factory) -> None:
        if self.screen is not None and not self.screen.close():
            return
        self.screen = factory()

    def show_start(self) -> None:
        self._replace(lambda: StartScreen(self.root, self.show_single,
                                          self.show_multi,
                                          self.show_compiler))

    def show_single(self) -> None:
        self._replace(lambda: GravaBinApp(self.root, self.show_start))

    def show_multi(self) -> None:
        self._replace(lambda: MultiFlashScreen(self.root, self.show_start))

    def show_compiler(self) -> None:
        self._replace(lambda: CompilerScreen(self.root, self.show_start))

    def _on_close(self) -> None:
        if self.screen is None or self.screen.close():
            self.root.destroy()


def _create_root() -> tk.Tk:
    """Cria a janela raiz usando o input method local do Xlib.

    Com um input method externo via XIM (ex.: ibus, padrão no GNOME), o Tk
    cria um contexto de entrada por widget conversando com o daemon — cada
    tela levava de 0,5 a 2 s para aparecer. O "@im=none" é o input method
    embutido do Xlib (teclas mortas e Compose continuam funcionando). O
    Xlib só lê XMODIFIERS ao abrir o display, então o valor original é
    restaurado logo depois: programas abertos daqui (editor, arduino-cli)
    continuam com o input method do usuário. GRAVABIN_KEEP_IM=1 desativa.
    """
    original = os.environ.get("XMODIFIERS")
    use_local = (original and "@im=" in original
                 and not os.environ.get("GRAVABIN_KEEP_IM"))
    if use_local:
        os.environ["XMODIFIERS"] = "@im=none"
    try:
        # className define o WM_CLASS da janela — deve casar com StartupWMClass no .desktop
        return tk.Tk(className="Gravabin")
    finally:
        if use_local:
            os.environ["XMODIFIERS"] = original


def main() -> None:
    root = _create_root()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    icons = []
    for path in list_logo_pngs():
        try:
            icons.append(tk.PhotoImage(file=path, master=root))
        except tk.TclError:
            pass
    if icons:
        try:
            root.iconphoto(True, *icons)
        except tk.TclError:
            pass
        root._icon_imgs = icons  # mantém referência p/ evitar coleta pelo GC
    Shell(root)
    root.mainloop()
