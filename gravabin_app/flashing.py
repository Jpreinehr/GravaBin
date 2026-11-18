"""Montagem dos argumentos do esptool, comum aos modos único e múltiplo."""

from __future__ import annotations

import os


def base_args(settings: dict, port: str) -> list[str]:
    return ["--chip", settings["chip"],
            "--port", port,
            "--baud", settings["baud"],
            "--before", "default_reset",
            "--after", "hard_reset"]


def write_flash_args(settings: dict, port: str,
                     files: list[tuple[str, str]]) -> list[str]:
    args = base_args(settings, port) + ["write_flash"]
    if settings.get("compress"):
        args.append("-z")
    if settings.get("erase"):
        args.append("--erase-all")
    if settings.get("verify"):
        args.append("--verify")
    args += ["--flash_mode", settings["flash_mode"],
             "--flash_freq", settings["flash_freq"],
             "--flash_size", settings["flash_size"]]
    for off, path in files:
        args += [off, path]
    return args


def validate_files(files: list[tuple[str, str]]) -> str | None:
    """Retorna a mensagem de erro, ou None se a lista puder ser gravada."""
    if not files:
        return "Marque ao menos um binário para gravar."
    for off, path in files:
        if not os.path.isfile(path):
            return f"Arquivo não encontrado:\n{path}"
        if not off.lower().startswith("0x"):
            return f"Offset inválido (use 0x...): {off!r}"
    return None
