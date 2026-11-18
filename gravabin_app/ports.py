"""Listagem das portas seriais que fazem sentido para gravar um ESP."""

from __future__ import annotations

import glob
import re

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    list_ports = None

# UARTs da placa-mãe (/dev/ttyS0..N): sempre presentes no Linux e nunca são
# o conversor USB-serial de um ESP — só poluem a lista.
_BUILTIN_UART = re.compile(r"/dev/ttyS\d+")


def _natural_key(dev: str) -> list:
    """Ordena ttyUSB2 antes de ttyUSB10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", dev)]


def list_serial_ports() -> list[str]:
    ports: set[str] = set()
    if list_ports is not None:
        for p in list_ports.comports():
            ports.add(p.device)
    for pat in ("/dev/ttyUSB*", "/dev/ttyACM*"):
        ports.update(glob.glob(pat))
    return sorted((p for p in ports if not _BUILTIN_UART.fullmatch(p)),
                  key=_natural_key)
