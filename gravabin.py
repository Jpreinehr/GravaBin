from __future__ import annotations

import glob
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import esptool  # type: ignore
except ImportError:  # pragma: no cover
    esptool = None

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    list_ports = None


APP_NAME = "GravaBin"
APP_VERSION = "1.0.0"

CHIPS = ["auto", "esp32", "esp32s2", "esp32s3", "esp32c3", "esp8266"]
BAUDS = ["115200", "230400", "460800", "921600", "1500000"]
FLASH_MODES = ["dio", "qio", "dout", "qout"]
FLASH_FREQS = ["40m", "80m", "26m", "20m"]
FLASH_SIZES = ["detect", "1MB", "2MB", "4MB", "8MB", "16MB"]

DEFAULT_ROWS = [
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xe000", "boot_app0.bin"),
    ("0x10000", "app.bin"),
    ("0x3D0000", "spiffs.bin (opcional)"),
]


# ---------------------------------------------------------------------------
class StdoutRedirector:
    """Redireciona stdout/stderr para uma fila consumida pela GUI."""

    def __init__(self, q: "queue.Queue[str]") -> None:
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:  # noqa: D401
        pass


# ---------------------------------------------------------------------------
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
            self.done_callback(ok)


# ---------------------------------------------------------------------------
class BinRow:
    def __init__(self, parent: tk.Widget, row: int,
                 offset: str = "", path_hint: str = "") -> None:
        self.var_use = tk.BooleanVar(value=False)
        self.var_offset = tk.StringVar(value=offset)
        self.var_path = tk.StringVar(value="")
        self.hint = path_hint

        self.chk = ttk.Checkbutton(parent, variable=self.var_use)
        self.chk.grid(row=row, column=0, padx=2, pady=2)

        self.ent_off = ttk.Entry(parent, textvariable=self.var_offset, width=10)
        self.ent_off.grid(row=row, column=1, padx=2, pady=2)

        self.ent_path = ttk.Entry(parent, textvariable=self.var_path, width=55)
        self.ent_path.grid(row=row, column=2, padx=2, pady=2, sticky="ew")

        self.btn = ttk.Button(parent, text="…", width=3, command=self._browse)
        self.btn.grid(row=row, column=3, padx=2, pady=2)

        ttk.Label(parent, text=path_hint, foreground="#888").grid(
            row=row, column=4, padx=4, sticky="w")

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


# ---------------------------------------------------------------------------
class GravaBinApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} - Gravador ESP {APP_VERSION}")
        root.geometry("980x720")
        root.minsize(820, 600)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: FlashWorker | None = None

        self._build_ui()
        self._refresh_ports()
        self.root.after(80, self._drain_log)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        # Linha 1: porta, baud, chip
        ttk.Label(top, text="Porta:").grid(row=0, column=0, sticky="e")
        self.cmb_port = ttk.Combobox(top, width=28, state="readonly")
        self.cmb_port.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        ttk.Button(top, text="↻", width=3, command=self._refresh_ports
                   ).grid(row=0, column=2, padx=2)

        ttk.Label(top, text="Baud:").grid(row=0, column=3, sticky="e")
        self.cmb_baud = ttk.Combobox(top, width=10, values=BAUDS,
                                     state="readonly")
        self.cmb_baud.set("460800")
        self.cmb_baud.grid(row=0, column=4, padx=4)

        ttk.Label(top, text="Chip:").grid(row=0, column=5, sticky="e")
        self.cmb_chip = ttk.Combobox(top, width=10, values=CHIPS,
                                     state="readonly")
        self.cmb_chip.set("esp32")
        self.cmb_chip.grid(row=0, column=6, padx=4)

        ttk.Label(top, text="Flash mode:").grid(row=1, column=0, sticky="e")
        self.cmb_mode = ttk.Combobox(top, width=10, values=FLASH_MODES,
                                     state="readonly")
        self.cmb_mode.set("dio")
        self.cmb_mode.grid(row=1, column=1, padx=4, pady=4, sticky="w")

        ttk.Label(top, text="Freq:").grid(row=1, column=3, sticky="e")
        self.cmb_freq = ttk.Combobox(top, width=10, values=FLASH_FREQS,
                                     state="readonly")
        self.cmb_freq.set("80m")
        self.cmb_freq.grid(row=1, column=4, padx=4)

        ttk.Label(top, text="Size:").grid(row=1, column=5, sticky="e")
        self.cmb_size = ttk.Combobox(top, width=10, values=FLASH_SIZES,
                                     state="readonly")
        self.cmb_size.set("detect")
        self.cmb_size.grid(row=1, column=6, padx=4)

        self.var_erase = tk.BooleanVar(value=False)
        self.var_compress = tk.BooleanVar(value=True)
        self.var_verify = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Apagar flash antes",
                        variable=self.var_erase).grid(row=2, column=1,
                                                      sticky="w", pady=4)
        ttk.Checkbutton(top, text="Comprimir (-z)",
                        variable=self.var_compress).grid(row=2, column=4,
                                                         sticky="w")

        box = ttk.LabelFrame(self.root, text="Binários a gravar", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        ttk.Label(box, text="Usar").grid(row=0, column=0)
        ttk.Label(box, text="Offset").grid(row=0, column=1)
        ttk.Label(box, text="Arquivo .bin").grid(row=0, column=2)
        ttk.Label(box, text="").grid(row=0, column=3)
        ttk.Label(box, text="Sugestão").grid(row=0, column=4, sticky="w")
        box.columnconfigure(2, weight=1)

        self.rows: list[BinRow] = []
        for i, (off, hint) in enumerate(DEFAULT_ROWS, start=1):
            self.rows.append(BinRow(box, i, off, hint))

        btns = ttk.Frame(self.root, padding=(10, 4))
        btns.pack(fill="x")

        self.btn_flash = ttk.Button(btns, text="Gravar",
                                    command=self.on_flash)
        self.btn_flash.pack(side="left", padx=4)

        self.btn_erase = ttk.Button(btns, text="Apagar Flash",
                                    command=self.on_erase)
        self.btn_erase.pack(side="left", padx=4)

        self.btn_mac = ttk.Button(btns, text="Ler MAC / Chip",
                                  command=self.on_read_mac)
        self.btn_mac.pack(side="left", padx=4)

        self.btn_clear = ttk.Button(btns, text="Limpar log",
                                    command=lambda: self.txt.delete("1.0", "end"))
        self.btn_clear.pack(side="right", padx=4)

        # Olhar dps ta bugado
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(2, 4))

        log_frame = ttk.LabelFrame(self.root, text="Console", padding=4)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.txt = tk.Text(log_frame, bg="#111", fg="#cfe", insertbackground="#fff",
                           font=("DejaVu Sans Mono", 10), wrap="none")
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.config(yscrollcommand=sb.set)

        # Status bar
        self.status = tk.StringVar(value="Pronto.")
        ttk.Label(self.root, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

    # ---------------- helpers ----------------
    def _refresh_ports(self) -> None:
        ports: list[str] = []
        if list_ports is not None:
            for p in list_ports.comports():
                ports.append(p.device)
    
        for pat in ("/dev/ttyUSB*", "/dev/ttyACM*"):
            for d in glob.glob(pat):
                if d not in ports:
                    ports.append(d)
        ports.sort()
        self.cmb_port["values"] = ports
        if ports and not self.cmb_port.get():
            self.cmb_port.set(ports[0])
        self.status.set(f"{len(ports)} porta(s) encontrada(s).")

    def _drain_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append(line)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_log)

    def _append(self, text: str) -> None:
        if text.startswith("\r"):
            # reescreve a última linha
            idx = self.txt.index("end-1c linestart")
            self.txt.delete(idx, "end-1c")
            self.txt.insert("end", text[1:])
        else:
            self.txt.insert("end", text)
        self.txt.see("end")

    def _check_ready(self) -> bool:
        if esptool is None:
            messagebox.showerror(APP_NAME,
                                 "Pacote 'esptool' não encontrado.\n"
                                 "Instale com: pip install esptool")
            return False
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(APP_NAME, "Já existe uma operação em andamento.")
            return False
        if not self.cmb_port.get():
            messagebox.showwarning(APP_NAME, "Selecione uma porta serial.")
            return False
        return True

    def _base_args(self) -> list[str]:
        args = ["--chip", self.cmb_chip.get(),
                "--port", self.cmb_port.get(),
                "--baud", self.cmb_baud.get(),
                "--before", "default_reset",
                "--after", "hard_reset"]
        return args

    def _start(self, args: list[str]) -> None:
        self._set_busy(True)
        self.worker = FlashWorker(args, self.log_queue, self._on_done)
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_flash, self.btn_erase, self.btn_mac):
            b.configure(state=state)
        if busy:
            self.progress.start(10)
            self.status.set("Executando…")
        else:
            self.progress.stop()

    def _on_done(self, ok: bool) -> None:
        def finish() -> None:
            self._set_busy(False)
            self.status.set("Concluído com sucesso." if ok else "Falhou. Veja o console.")
        self.root.after(0, finish)

    # ---------------- ações ----------------
    def on_flash(self) -> None:
        if not self._check_ready():
            return
        files = [r.values() for r in self.rows if r.is_active()]
        if not files:
            messagebox.showwarning(APP_NAME,
                                   "Marque ao menos um binário para gravar.")
            return
        for off, path in files:
            if not os.path.isfile(path):
                messagebox.showerror(APP_NAME, f"Arquivo não encontrado:\n{path}")
                return
            if not off.lower().startswith("0x"):
                messagebox.showerror(APP_NAME,
                                     f"Offset inválido (use 0x...): {off!r}")
                return

        args = self._base_args()
        args += ["write_flash"]
        if self.var_compress.get():
            args.append("-z")
        if self.var_erase.get():
            args.append("--erase-all")
        if self.var_verify.get():
            args.append("--verify")
        args += ["--flash_mode", self.cmb_mode.get(),
                 "--flash_freq", self.cmb_freq.get(),
                 "--flash_size", self.cmb_size.get()]
        for off, path in files:
            args += [off, path]

        self._start(args)

    def on_erase(self) -> None:
        if not self._check_ready():
            return
        if not messagebox.askyesno(APP_NAME,
                                   "Apagar TODA a memória flash do dispositivo?"):
            return
        self._start(self._base_args() + ["erase_flash"])

    def on_read_mac(self) -> None:
        if not self._check_ready():
            return
        self._start(self._base_args() + ["read_mac"])


# ---------------------------------------------------------------------------
def main() -> None:
    root = tk.Tk()
    GravaBinApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
