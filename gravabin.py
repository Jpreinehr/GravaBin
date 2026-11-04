#!/usr/bin/env python3
"""Ponto de entrada do GravaBin — a implementação vive em gravabin_app/."""

from __future__ import annotations

try:
    from setproctitle import setproctitle
    # Sem isto, o processo aparece como "python3" no gerenciador de tarefas
    # (o kernel só conhece o interpretador, não o script). Renomear para
    # "gravabin" também casa com o ícone "gravabin" do tema hicolor,
    # permitindo que monitores de sistema o encontrem por nome do processo.
    setproctitle("gravabin")
except ImportError:  # pragma: no cover
    pass

from gravabin_app.main import main

if __name__ == "__main__":
    main()
