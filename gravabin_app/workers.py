"""Threads de trabalho: gravação via esptool e monitor serial.

Nenhuma classe deste módulo chama métodos do Tkinter. O Tkinter não é
thread-safe: chamar métodos do root/widgets a partir de outra thread pode
corromper o interpretador Tcl e travar a aplicação de forma intermitente.
Por isso as threads só se comunicam com a GUI através da `log_queue`
(thread-safe) — nunca chamam `done_callback` diretamente, apenas colocam um
marcador `Done` na fila. Quem invoca o callback é sempre a thread principal,
dentro do laço de esvaziamento da fila (`GravaBinApp._drain_log`).
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime

try:
    import esptool  # type: ignore
except ImportError:  # pragma: no cover
    esptool = None

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    serial = None


class StdoutRedirector:
    """Redireciona stdout/stderr para uma fila consumida pela GUI."""

    def __init__(self, q: "queue.Queue[str]") -> None:
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:  # noqa: D401
        pass


class Done:
    """Sinaliza, via a fila, que uma thread de trabalho terminou."""

    def __init__(self, callback, ok: bool) -> None:
        self.callback = callback
        self.ok = ok


class Call:
    """Pede à thread principal, via a fila, que chame `fn(*args)`."""

    def __init__(self, fn, *args) -> None:
        self.fn = fn
        self.args = args

    def run(self) -> None:
        self.fn(*self.args)


class BackgroundTask(threading.Thread):
    """Roda `fn()` fora da GUI e entrega `callback(ok, resultado|exceção)`."""

    def __init__(self, fn, log_queue: "queue.Queue", callback) -> None:
        super().__init__(daemon=True)
        self.fn = fn
        self.log_queue = log_queue
        self.callback = callback

    def run(self) -> None:
        try:
            result, ok = self.fn(), True
        except Exception as exc:  # noqa: BLE001
            result, ok = exc, False
        self.log_queue.put(Call(self.callback, ok, result))


# Sequências ANSI (cores do log do ESP) e controles que quebram editores/Tk.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_serial_text(text: str) -> str:
    """Remove ANSI, NUL e demais controles (mantém \\n e \\t)."""
    return _CTRL.sub("", _ANSI.sub("", text))


# Barra de download do arduino-cli: "... 2.49 MiB / 4.45 MiB   55.89% 00m01s".
_PROGRESS = re.compile(r"\d+(\.\d+)?%(\s+\d+m\d+s)?$")


class CommandWorker(threading.Thread):
    """Roda um comando externo e manda a saída, linha a linha, para a fila.

    Linhas de progresso consecutivas (com '%', ex.: downloads) chegam com
    '\\r' na frente, para o console reescrever a linha em vez de empilhar.
    """

    def __init__(self, cmd: list[str], log_queue: "queue.Queue",
                 done_callback, env: dict | None = None,
                 fail_markers: tuple[str, ...] = ()) -> None:
        super().__init__(daemon=True)
        self.cmd = cmd
        self.log_queue = log_queue
        self.done_callback = done_callback
        self.env = env
        # Textos que indicam falha mesmo com código de saída 0.
        self.fail_markers = fail_markers
        self._saw_failure = False
        self._proc: subprocess.Popen | None = None
        self._cancelled = threading.Event()

    def run(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, errors="replace",
                bufsize=1, env=self.env)
        except OSError as exc:
            self.log_queue.put(f"[ERRO] {exc}\n")
            self.log_queue.put(Done(self.done_callback, False))
            return
        if self._cancelled.is_set():
            self._proc.terminate()
        last_progress = False
        for line in self._proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            if any(m in line for m in self.fail_markers):
                self._saw_failure = True
            progress = bool(_PROGRESS.search(line))
            if progress:
                # Fica sem '\n' para a próxima linha de progresso reescrevê-la.
                self.log_queue.put(("\r" if last_progress else "") + line)
            else:
                self.log_queue.put(("\n" if last_progress else "") + line + "\n")
            last_progress = progress
        if last_progress:
            self.log_queue.put("\n")
        code = self._proc.wait()
        if self._cancelled.is_set():
            self.log_queue.put("[cancelado]\n")
        ok = code == 0 and not self._saw_failure and not self._cancelled.is_set()
        if code == 0 and self._saw_failure:
            self.log_queue.put("[ERRO] a ferramenta relatou erro fatal, "
                               "embora tenha saído com código 0.\n")
        self.log_queue.put(Done(self.done_callback, ok))

    def stop(self) -> None:
        self._cancelled.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


class MonitorText(str):
    """Texto vindo do monitor serial (a GUI guarda à parte para exportar)."""


class FlashWorker(threading.Thread):
    def __init__(self, args: list[str], log_queue: "queue.Queue[str]",
                 done_callback) -> None:
        super().__init__(daemon=True)
        self.args = args
        self.log_queue = log_queue
        self.done_callback = done_callback

    def run(self) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        redir = StdoutRedirector(self.log_queue)
        sys.stdout = redir
        sys.stderr = redir
        ok = False
        try:
            print(">>> esptool " + " ".join(self.args) + "\n")
            esptool.main(self.args)
            ok = True
        except SystemExit as e:
            ok = (e.code in (0, None))
            if not ok:
                print(f"\n[esptool] saiu com código {e.code}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERRO] {exc.__class__.__name__}: {exc}")
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            self.log_queue.put(Done(self.done_callback, ok))


class PortLine:
    """Uma linha de saída do esptool de uma porta (modo múltiplo)."""

    def __init__(self, port: str, text: str) -> None:
        self.port = port
        self.text = text


class ProcessFlashWorker(threading.Thread):
    """Roda o esptool em um subprocesso, para várias portas em paralelo.

    O FlashWorker roda o esptool no próprio processo redirecionando o
    sys.stdout global — isso não funciona com várias gravações simultâneas,
    então aqui cada porta tem seu próprio processo e sua própria saída.
    """

    def __init__(self, port: str, args: list[str],
                 log_queue: "queue.Queue", done_callback) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.args = args
        self.log_queue = log_queue
        self.done_callback = done_callback
        self._proc: subprocess.Popen | None = None
        self._cancelled = threading.Event()

    def run(self) -> None:
        cmd = [sys.executable, "-m", "esptool", *self.args]
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, errors="replace",
                bufsize=1, env=env)
        except OSError as exc:
            self.log_queue.put(PortLine(self.port, f"[ERRO] {exc}"))
            self.log_queue.put(Done(self.done_callback, False))
            return
        if self._cancelled.is_set():
            self._proc.terminate()
        # Modo texto: '\r' das barras de progresso também quebra linha.
        for line in self._proc.stdout:
            line = line.rstrip()
            if line:
                self.log_queue.put(PortLine(self.port, line))
        code = self._proc.wait()
        if self._cancelled.is_set():
            self.log_queue.put(PortLine(self.port, "[cancelado]"))
        self.log_queue.put(
            Done(self.done_callback, code == 0 and not self._cancelled.is_set()))

    def stop(self) -> None:
        self._cancelled.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


class SerialMonitor(threading.Thread):
    """Lê continuamente a porta serial e envia o texto para a fila de log."""

    def __init__(self, port: str, baud: int, log_queue: "queue.Queue[str]",
                 done_callback, timestamps: bool = True) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.log_queue = log_queue
        self.done_callback = done_callback
        # Pode ser alterado pela GUI com o monitor aberto (atribuição atômica).
        self.timestamps = timestamps
        self._at_line_start = True
        # Não chamar de `_stop`: sobrescreveria Thread._stop e quebraria join().
        self._stop_evt = threading.Event()
        self._ser = None

    def _put(self, text: str) -> None:
        self.log_queue.put(MonitorText(text))

    def _stamp(self, text: str) -> str:
        """Prefixa cada linha nova com data/hora de recebimento."""
        if not self.timestamps:
            self._at_line_start = text.endswith("\n")
            return text
        stamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S.%f")[:-3] + "] "
        out: list[str] = []
        parts = text.split("\n")
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if part or not last:
                if self._at_line_start:
                    out.append(stamp)
                out.append(part)
                self._at_line_start = False
            if not last:
                out.append("\n")
                self._at_line_start = True
        return "".join(out)

    def run(self) -> None:
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
        except Exception as exc:  # noqa: BLE001
            self._put(f"\n[monitor] erro ao abrir {self.port}: {exc}\n")
            self.log_queue.put(Done(self.done_callback, False))
            return
        self._put(f"\n[monitor] {self.port} @ {self.baud} bps — aberto\n")
        try:
            while not self._stop_evt.is_set():
                try:
                    # Bloqueia até 1 byte (ou timeout) e lê o que já chegou:
                    # read(4096) esperaria o timeout inteiro sem encher o buffer.
                    data = self._ser.read(max(1, self._ser.in_waiting))
                except Exception as exc:  # noqa: BLE001
                    self._put(f"\n[monitor] leitura interrompida: {exc}\n")
                    break
                if data:
                    text = data.decode("utf-8", errors="replace")
                    # Normaliza CR/CRLF: o console trata '\r' como reescrita.
                    text = text.replace("\r\n", "\n").replace("\r", "\n")
                    text = sanitize_serial_text(text)
                    if not text:
                        continue
                    self._put(self._stamp(text))
        finally:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self._put(f"\n[monitor] {self.port} — fechado\n")
            self.log_queue.put(Done(self.done_callback, True))

    def stop(self) -> None:
        self._stop_evt.set()
