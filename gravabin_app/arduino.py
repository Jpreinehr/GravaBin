"""Integração com o arduino-cli: placas, bibliotecas, compilação e upload.

Usa as mesmas pastas do Arduino IDE 1.8.x (~/.arduino15 para placas e
índices, sketchbook/libraries para bibliotecas), então o que for instalado
por um aparece no outro. As URLs adicionais do Gerenciador de Placas do IDE
(preferences.txt) também são aproveitadas.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

from .constants import (
    ARDUINO_BUILD_DIR,
    ARDUINO_CLI_PATHS,
    CHIPS,
    COMPILER_STATE_PATH,
    DEFAULT_BOARD_URLS,
    DEFAULT_SETTINGS,
    FLASH_FREQS,
    FLASH_MODES,
    IDE_PREFERENCES_PATH,
)


class CliError(Exception):
    """Falha de um comando do arduino-cli (mensagem para o usuário)."""


def find_cli() -> str | None:
    for path in ARDUINO_CLI_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("arduino-cli")


def _ide_preferences() -> dict[str, str]:
    prefs: dict[str, str] = {}
    try:
        with open(IDE_PREFERENCES_PATH, encoding="utf-8") as fh:
            for line in fh:
                key, sep, value = line.rstrip("\n").partition("=")
                if sep:
                    prefs[key.strip()] = value.strip()
    except OSError:
        pass
    return prefs


# ---------------------------------------------------------------------------
def load_state() -> dict:
    """Estado do modo compilador (último sketch, placa, opções, URLs...)."""
    try:
        with open(COMPILER_STATE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(COMPILER_STATE_PATH), exist_ok=True)
    with open(COMPILER_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)


def board_urls(extra: list[str] | None = None) -> list[str]:
    """URLs de índices de placas: padrão (ESP) + IDE + as do usuário."""
    ide = _ide_preferences().get("boardsmanager.additional.urls", "")
    urls: list[str] = []
    for url in [*DEFAULT_BOARD_URLS, *ide.split(","), *(extra or [])]:
        url = url.strip()
        if url and url not in urls:
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
class ArduinoCli:
    def __init__(self, path: str, extra_urls: list[str] | None = None) -> None:
        self.path = path
        self.extra_urls = list(extra_urls or [])
        self.env = dict(os.environ)
        # Sketchbook personalizado no IDE -> bibliotecas ficam lá.
        sketchbook = _ide_preferences().get("sketchbook.path")
        if sketchbook:
            self.env["ARDUINO_DIRECTORIES_USER"] = sketchbook
        # Permite "Instalar .zip" sem editar o arduino-cli.yaml.
        self.env["ARDUINO_LIBRARY_ENABLE_UNSAFE_INSTALL"] = "true"

    def cmd(self, *args: str) -> list[str]:
        return [self.path, "--additional-urls",
                ",".join(board_urls(self.extra_urls)), *args]

    def run_json(self, *args: str, timeout: float = 300) -> dict:
        """Roda um comando com --format json (bloqueia: chamar fora da GUI)."""
        try:
            proc = subprocess.run(self.cmd(*args, "--format", "json"),
                                  capture_output=True, text=True,
                                  errors="replace", timeout=timeout,
                                  env=self.env, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CliError(str(exc)) from exc
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip()
            try:
                msg = json.loads(msg).get("error", msg)
            except (ValueError, AttributeError):
                pass
            raise CliError(msg or f"arduino-cli saiu com código {proc.returncode}")
        try:
            data = json.loads(proc.stdout or "{}")
        except ValueError as exc:
            raise CliError("Resposta inválida do arduino-cli.") from exc
        return data if isinstance(data, dict) else {}

    # ---------------- consultas ----------------
    def list_boards(self) -> list[tuple[str, str]]:
        """(nome, fqbn) das placas dos cores instalados."""
        boards = self.run_json("board", "listall").get("boards") or []
        out = [(b.get("name", ""), b.get("fqbn", "")) for b in boards
               if b.get("fqbn")]
        return sorted(out, key=lambda b: (b[1].rsplit(":", 1)[0],
                                          b[0].lower()))

    def board_options(self, fqbn: str) -> list[dict]:
        """Menus da placa (Ferramentas do IDE): option, label e valores."""
        data = self.run_json("board", "details", "-b", fqbn)
        return data.get("config_options") or []

    def platforms(self) -> list[dict]:
        """Cores disponíveis nos índices: id, nome, instalada, mais recente."""
        data = self.run_json("core", "search")
        out = []
        for p in data.get("platforms") or []:
            latest = p.get("latest_version", "")
            release = (p.get("releases") or {}).get(latest) or {}
            out.append({"id": p.get("id", ""),
                        "name": release.get("name") or p.get("id", ""),
                        "installed": p.get("installed_version", ""),
                        "latest": latest,
                        "maintainer": p.get("maintainer", "")})
        return sorted(out, key=lambda p: (not p["installed"], p["id"]))

    def search_libraries(self, query: str) -> list[dict]:
        data = self.run_json("lib", "search", "--omit-releases-details",
                             *query.split())
        out = []
        for lib in data.get("libraries") or []:
            latest = lib.get("latest") or {}
            out.append({"name": lib.get("name", ""),
                        "version": latest.get("version", ""),
                        "author": latest.get("author", ""),
                        "sentence": latest.get("sentence", ""),
                        "versions": lib.get("available_versions") or []})
        return out

    def installed_libraries(self) -> list[dict]:
        data = self.run_json("lib", "list")
        out = []
        for item in data.get("installed_libraries") or []:
            lib = item.get("library") or {}
            if lib.get("location") not in (None, "user"):
                continue  # embutidas no core: não dá para remover/atualizar
            out.append({"name": lib.get("name", ""),
                        "version": lib.get("version", ""),
                        "latest": (item.get("release") or {}).get("version", ""),
                        "sentence": lib.get("sentence", "")})
        return sorted(out, key=lambda lib: lib["name"].lower())

    def build_properties(self, fqbn: str, sketch: str) -> dict[str, str]:
        try:
            proc = subprocess.run(
                self.cmd("compile", "-b", fqbn, "--show-properties", sketch),
                capture_output=True, text=True, errors="replace",
                timeout=120, env=self.env, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CliError(str(exc)) from exc
        if proc.returncode != 0:
            raise CliError(proc.stderr.strip() or "Falha ao ler propriedades.")
        props = {}
        for line in proc.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                props[key] = value
        return props

    # ---------------- comandos longos (rodam num CommandWorker) ----------
    def compile_cmd(self, fqbn: str, sketch: str, build_path: str,
                    verbose: bool) -> list[str]:
        return self.cmd("compile", "-b", fqbn, "--build-path", build_path,
                        *(["-v"] if verbose else []), sketch)

    def upload_cmd(self, fqbn: str, sketch: str, build_path: str, port: str,
                   verbose: bool) -> list[str]:
        return self.cmd("upload", "-b", fqbn, "-p", port,
                        "--input-dir", build_path,
                        *(["-v"] if verbose else []), sketch)


# ---------------------------------------------------------------------------
def sketch_dir(path: str) -> str:
    """Aceita o .ino ou a pasta do sketch; devolve a pasta."""
    return os.path.dirname(path) if os.path.isfile(path) else path


def sketch_problem(path: str) -> str | None:
    """Mensagem se o sketch não puder ser compilado (regra do Arduino)."""
    folder = sketch_dir(path)
    name = os.path.basename(os.path.normpath(folder))
    if not os.path.isfile(os.path.join(folder, name + ".ino")):
        return (f"O sketch precisa estar numa pasta com o mesmo nome do "
                f".ino principal:\n{folder}/{name}.ino")
    return None


def build_path_for(sketch: str) -> str:
    """Pasta de build fixa por sketch (recompilações ficam incrementais)."""
    folder = os.path.abspath(sketch_dir(sketch))
    digest = hashlib.sha1(folder.encode()).hexdigest()[:10]
    return os.path.join(ARDUINO_BUILD_DIR,
                        f"{os.path.basename(folder)}-{digest}")


def full_fqbn(fqbn: str, options: dict[str, str]) -> str:
    if not options:
        return fqbn
    return fqbn + ":" + ",".join(f"{k}={v}" for k, v in options.items())


def built_images(build_path: str, props: dict[str, str]) -> list[tuple[str, str]]:
    """(offset, arquivo) para gravar o resultado da compilação com o esptool.

    ESP32 core 3.x gera um .merged.bin (bootloader + partições + app) que vai
    em 0x0. Em cores ESP32 mais antigos, monta as 4 imagens com os offsets
    padrão. ESP8266 é uma imagem só, em 0x0.
    """
    project = props.get("build.project_name", "")
    base = os.path.join(build_path, project)
    merged = base + ".merged.bin"
    app = base + ".bin"
    if os.path.isfile(merged):
        return [("0x0", merged)]
    mcu = props.get("build.mcu", "")
    if mcu.startswith("esp32"):
        boot_app0 = os.path.join(props.get("runtime.platform.path", ""),
                                 "tools", "partitions", "boot_app0.bin")
        images = [(props.get("build.bootloader_addr", "0x1000"),
                   base + ".bootloader.bin"),
                  ("0x8000", base + ".partitions.bin"),
                  ("0xe000", boot_app0),
                  ("0x10000", app)]
        missing = [p for _, p in images if not os.path.isfile(p)]
        if missing:
            raise CliError("Binários do ESP32 não encontrados:\n"
                           + "\n".join(missing))
        return images
    if os.path.isfile(app):
        return [("0x0", app)]
    raise CliError(f"Binário compilado não encontrado em {build_path}.")


def settings_from_props(props: dict[str, str]) -> dict:
    """Configurações de gravação (preset) a partir das propriedades da placa."""
    settings = dict(DEFAULT_SETTINGS)
    mcu = props.get("build.mcu", "")
    settings["chip"] = mcu if mcu in CHIPS else "auto"
    mode = props.get("build.flash_mode", "")
    if mode in FLASH_MODES:
        settings["flash_mode"] = mode
    freq = props.get("build.flash_freq", "")
    freq = freq + "m" if freq.isdigit() else freq
    if freq in FLASH_FREQS:
        settings["flash_freq"] = freq
    return settings
