"""Constantes de configuração, caminhos e listas de opções da interface."""

from __future__ import annotations

import os

APP_NAME = "GravaBin"
APP_VERSION = "1.1.0"

# Diretório raiz da aplicação: pai do pacote gravabin_app/, tanto rodando
# do fonte (repo root) quanto instalado (/usr/lib/gravabin/).
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Diretórios onde procurar os PNGs do logo (rodando do fonte ou instalado).
LOGO_DIRS = [
    os.path.join(SCRIPT_DIR, "GravaBin Logo Design", "export", "icones"),
    os.path.join(SCRIPT_DIR, "icones"),
    "/usr/lib/gravabin/icones",
    "/usr/share/gravabin/icones",
]

PRESETS_PATH = os.path.expanduser("~/.config/gravabin/presets.json")
DEFAULT_PRESET_NAME = "Padrão"

# Presets compartilháveis: zip com preset.json + binários.
PRESET_EXT = ".gravabin"
# Onde os binários de presets importados são extraídos.
IMPORTED_PRESETS_DIR = os.path.expanduser("~/.local/share/gravabin/presets")

# ---- Modo compilador (arduino-cli) ----
# Binário embutido no .deb; rodando do fonte, bin/ do repo ou o do PATH.
ARDUINO_CLI_PATHS = [
    "/usr/lib/gravabin/bin/arduino-cli",
    os.path.join(SCRIPT_DIR, "bin", "arduino-cli"),
]
COMPILER_STATE_PATH = os.path.expanduser("~/.config/gravabin/compiler.json")
ARDUINO_BUILD_DIR = os.path.expanduser("~/.cache/gravabin/build")
# Preferências do Arduino IDE 1.8.x (URLs de placas, sketchbook).
IDE_PREFERENCES_PATH = os.path.expanduser("~/.arduino15/preferences.txt")
DEFAULT_BOARD_URLS = [
    "https://espressif.github.io/arduino-esp32/package_esp32_index.json",
    "https://arduino.esp8266.com/stable/package_esp8266com_index.json",
]

CHIPS = ["auto", "esp32", "esp32s2", "esp32s3", "esp32c3", "esp8266"]
BAUDS = ["115200", "230400", "460800", "921600", "1500000"]
FLASH_MODES = ["dio", "qio", "dout", "qout"]
FLASH_FREQS = ["40m", "80m", "26m", "20m"]
FLASH_SIZES = ["detect", "1MB", "2MB", "4MB", "8MB", "16MB"]

# Configurações de gravação guardadas em cada preset.
DEFAULT_SETTINGS = {
    "chip": "esp32",
    "baud": "460800",
    "flash_mode": "dio",
    "flash_freq": "80m",
    "flash_size": "detect",
    "erase": False,
    "compress": True,
    "verify": False,
}

MONITOR_BAUDS =["9600", "57600", "74880", "115200", "230400", "460800", "921600"]

DEFAULT_ROWS = [
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xe000", "boot_app0.bin"),
    ("0x10000", "app.bin"),
    ("0x3D0000", "spiffs.bin (opcional)"),
]

# Estrutura de linhas usada por um preset novo / padrão.
DEFAULT_ROWS_DATA = [
    {"offset": off, "path": "", "hint": hint, "use": False}
    for off, hint in DEFAULT_ROWS
]

# Console: linhas mantidas na tela (o log do monitor para exportar é separado)
# e tempo máximo gasto esvaziando a fila a cada ciclo, para a GUI não travar
# com saída muito rápida.
CONSOLE_MAX_LINES = 5000
DRAIN_BUDGET_S = 0.03
MONITOR_LOG_MAX_CHUNKS = 200_000
