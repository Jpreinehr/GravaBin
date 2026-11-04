"""Leitura e gravação dos presets em ~/.config/gravabin/presets.json.

Também exporta/importa um preset como pacote `.gravabin` (zip com
`preset.json` + os binários), para compartilhar com outras máquinas.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile

from .constants import (
    APP_VERSION,
    DEFAULT_PRESET_NAME,
    DEFAULT_ROWS_DATA,
    DEFAULT_SETTINGS,
    IMPORTED_PRESETS_DIR,
    PRESETS_PATH,
)

_FORMAT = "gravabin-preset"
_FORMAT_VERSION = 1
_MANIFEST = "preset.json"


class PresetError(Exception):
    """Erro ao exportar/importar um pacote de preset (mensagem para o usuário)."""


def load_presets() -> tuple[dict, list[dict]]:
    """Retorna (preset padrão, outros presets), lendo do disco.

    O preset padrão sempre existe: se não houver um salvo, usa as linhas
    padrão (DEFAULT_ROWS_DATA).
    """
    data: list[dict] = []
    try:
        with open(PRESETS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = []
    if not isinstance(data, list):
        data = []

    default = next((p for p in data
                    if p.get("name") == DEFAULT_PRESET_NAME), None)
    if default is None:
        default = {"name": DEFAULT_PRESET_NAME, "rows": DEFAULT_ROWS_DATA}
    others = [p for p in data if p.get("name") != DEFAULT_PRESET_NAME]
    return default, others


def save_presets(dumps: list[dict]) -> None:
    """Grava a lista de presets (cada um no formato de PresetPanel.dump())."""
    os.makedirs(os.path.dirname(PRESETS_PATH), exist_ok=True)
    with open(PRESETS_PATH, "w", encoding="utf-8") as fh:
        json.dump(dumps, fh, indent=2, ensure_ascii=False)


def clean_settings(settings) -> dict | None:
    """Mantém só as chaves conhecidas, com o tipo esperado."""
    if not isinstance(settings, dict):
        return None
    out = {}
    for key, default in DEFAULT_SETTINGS.items():
        value = settings.get(key)
        if isinstance(value, type(default)):
            out[key] = value
    return out or None


# ---------------------------------------------------------------------------
def export_preset(preset: dict, dest: str) -> None:
    """Grava `preset` (formato de PresetPanel.dump()) em um pacote .gravabin."""
    rows_out: list[dict] = []
    files: list[tuple[str, str]] = []
    for i, row in enumerate(preset.get("rows") or []):
        path = (row.get("path") or "").strip()
        entry = {"use": bool(row.get("use")),
                 "offset": row.get("offset", ""),
                 "hint": row.get("hint", ""),
                 "file": None}
        if path:
            if os.path.isfile(path):
                arc = f"bins/{i}_{os.path.basename(path)}"
                entry["file"] = arc
                files.append((path, arc))
            elif entry["use"]:
                raise PresetError(f"Arquivo não encontrado:\n{path}")
        rows_out.append(entry)

    manifest = {
        "format": _FORMAT,
        "version": _FORMAT_VERSION,
        "app_version": APP_VERSION,
        "name": preset.get("name", "Preset"),
        "settings": preset.get("settings"),
        "rows": rows_out,
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_MANIFEST, json.dumps(manifest, indent=2,
                                          ensure_ascii=False))
        for src, arc in files:
            zf.write(src, arc)


def _unique_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


def _slug(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("._") or "preset"


def add_built_preset(name: str, images: list[tuple[str, str]],
                     settings: dict) -> str:
    """Cria um preset a partir de binários compilados e grava em disco.

    Os binários são copiados para IMPORTED_PRESETS_DIR/<nome>/, para que
    recompilar o sketch não altere o preset. Devolve o nome final (com
    sufixo " (2)"… se já existir).
    """
    default, others = load_presets()
    name = _unique_name(name, {default.get("name")}
                        | {p.get("name") for p in others})
    dest_dir = os.path.join(IMPORTED_PRESETS_DIR, _slug(name))
    shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)
    rows = []
    for offset, src in images:
        path = os.path.join(dest_dir, os.path.basename(src))
        shutil.copyfile(src, path)
        rows.append({"use": True, "offset": offset, "path": path,
                     "hint": os.path.basename(src)})
    save_presets([default, *others,
                  {"name": name, "rows": rows, "settings": settings}])
    return name


def import_preset(src: str, taken_names: set[str]) -> dict:
    """Lê um pacote .gravabin, extrai os binários e devolve o preset.

    O nome recebe um sufixo " (2)", " (3)"… se já existir em `taken_names`.
    Os binários vão para IMPORTED_PRESETS_DIR/<nome>/ e as linhas do preset
    passam a apontar para eles.
    """
    try:
        zf = zipfile.ZipFile(src)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PresetError(f"Arquivo inválido: {exc}") from exc
    with zf:
        try:
            manifest = json.loads(zf.read(_MANIFEST).decode("utf-8"))
        except (KeyError, ValueError) as exc:
            raise PresetError("O arquivo não é um preset do GravaBin.") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != _FORMAT:
            raise PresetError("O arquivo não é um preset do GravaBin.")
        if manifest.get("version", 0) > _FORMAT_VERSION:
            raise PresetError("Preset criado por uma versão mais nova do "
                              "GravaBin. Atualize o programa para importá-lo.")

        name = _unique_name(str(manifest.get("name") or "Preset").strip()
                            or "Preset", taken_names)
        dest_dir = os.path.join(IMPORTED_PRESETS_DIR, _slug(name))
        # O nome é único entre os presets, então o diretório é só deste.
        shutil.rmtree(dest_dir, ignore_errors=True)
        os.makedirs(dest_dir, exist_ok=True)

        members = set(zf.namelist())
        rows: list[dict] = []
        for row in manifest.get("rows") or []:
            if not isinstance(row, dict):
                continue
            path = ""
            arc = row.get("file")
            # Só o nome-base: um zip malicioso não escapa de dest_dir.
            base = os.path.basename(arc) if isinstance(arc, str) else ""
            if base and arc in members:
                path = os.path.join(dest_dir, base)
                with zf.open(arc) as fin, open(path, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
            rows.append({"use": bool(row.get("use")) and bool(path),
                         "offset": str(row.get("offset", "")),
                         "path": path,
                         "hint": str(row.get("hint", ""))})

    preset = {"name": name, "rows": rows}
    settings = clean_settings(manifest.get("settings"))
    if settings:
        preset["settings"] = settings
    return preset
