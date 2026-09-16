from __future__ import annotations

import glob
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    import esptool  # type: ignore
except ImportError:  # pragma: no cover
    esptool = None

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    serial = None

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    list_ports = None


APP_NAME = "GravaBin"
APP_VERSION = "1.0.1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Diretórios onde procurar os PNGs do logo (rodando do fonte ou instalado).
LOGO_DIRS = [
    os.path.join(SCRIPT_DIR, "GravaBin Logo Design", "export", "icones"),
    os.path.join(SCRIPT_DIR, "icones"),
    "/usr/lib/gravabin/icones",
    "/usr/share/gravabin/icones",
]

PRESETS_PATH = os.path.expanduser("~/.config/gravabin/presets.json")
DEFAULT_PRESET_NAME = "Padrão"

CHIPS = ["auto", "esp32", "esp32s2", "esp32s3", "esp32c3", "esp8266"]
BAUDS = ["115200", "230400", "460800", "921600", "1500000"]
FLASH_MODES = ["dio", "qio", "dout", "qout"]
FLASH_FREQS = ["40m", "80m", "26m", "20m"]
FLASH_SIZES = ["detect", "1MB", "2MB", "4MB", "8MB", "16MB"]

MONITOR_BAUDS = ["9600", "57600", "74880", "115200", "230400", "460800", "921600"]

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
class SerialMonitor(threading.Thread):
    """Lê continuamente a porta serial e envia o texto para a fila de log."""

    def __init__(self, port: str, baud: int, log_queue: "queue.Queue[str]",
                 done_callback) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.log_queue = log_queue
        self.done_callback = done_callback
        self._stop = threading.Event()
        self._ser = None

    def run(self) -> None:
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(
                f"\n[monitor] erro ao abrir {self.port}: {exc}\n")
            self.done_callback(False)
            return
        self.log_queue.put(
            f"\n[monitor] {self.port} @ {self.baud} bps — aberto\n")
        try:
            while not self._stop.is_set():
                try:
                    data = self._ser.read(4096)
                except Exception as exc:  # noqa: BLE001
                    self.log_queue.put(f"\n[monitor] leitura interrompida: {exc}\n")
                    break
                if data:
                    text = data.decode("utf-8", errors="replace")
                    # Normaliza CR/CRLF: o console trata '\r' como reescrita.
                    text = text.replace("\r\n", "\n").replace("\r", "\n")
                    self.log_queue.put(text)
        finally:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.log_queue.put(f"\n[monitor] {self.port} — fechado\n")
            self.done_callback(True)

    def stop(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------------------
class BinRow:
    def __init__(self, parent: tk.Widget, offset: str = "", path: str = "",
                 hint: str = "", use: bool = False) -> None:
        self.var_use = tk.BooleanVar(value=use)
        self.var_offset = tk.StringVar(value=offset)
        self.var_path = tk.StringVar(value=path)
        self.hint = hint

        self.chk = ttk.Checkbutton(parent, variable=self.var_use)
        self.ent_off = ttk.Entry(parent, textvariable=self.var_offset, width=10)
        self.ent_path = ttk.Entry(parent, textvariable=self.var_path, width=55)
        self.btn = ttk.Button(parent, text="…", width=3, command=self._browse)
        self.lbl = ttk.Label(parent, text=hint, foreground="#888")

    def grid(self, row: int) -> None:
        self.chk.grid(row=row, column=0, padx=2, pady=2)
        self.ent_off.grid(row=row, column=1, padx=2, pady=2)
        self.ent_path.grid(row=row, column=2, padx=2, pady=2, sticky="ew")
        self.btn.grid(row=row, column=3, padx=2, pady=2)
        self.lbl.grid(row=row, column=4, padx=4, sticky="w")

    def destroy(self) -> None:
        for w in (self.chk, self.ent_off, self.ent_path, self.btn, self.lbl):
            w.destroy()

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

    def data(self) -> dict:
        return {
            "use": self.var_use.get(),
            "offset": self.var_offset.get().strip(),
            "path": self.var_path.get().strip(),
            "hint": self.hint,
        }


# ---------------------------------------------------------------------------
class PresetPanel(ttk.Frame):
    """Uma aba de preset: tabela de binários (offset + arquivo)."""

    def __init__(self, parent: tk.Widget, name: str,
                 rows_data: list[dict] | None = None,
                 is_default: bool = False) -> None:
        super().__init__(parent, padding=8)
        self.name = name
        self.is_default = is_default

        self.table = ttk.Frame(self)
        self.table.pack(fill="x")
        self.table.columnconfigure(2, weight=1)

        for col, txt in enumerate(
                ("Usar", "Offset", "Arquivo .bin", "", "Sugestão")):
            ttk.Label(self.table, text=txt).grid(
                row=0, column=col, sticky="w" if col >= 2 else "")

        # A quantidade de linhas é fixa (uma por binário típico do ESP);
        # os valores salvos são sobrepostos por índice.
        saved = rows_data or []
        self.rows: list[BinRow] = []
        for i, base in enumerate(DEFAULT_ROWS_DATA):
            s = saved[i] if i < len(saved) else {}
            row = BinRow(self.table,
                         s.get("offset", base["offset"]),
                         s.get("path", ""),
                         base["hint"],
                         s.get("use", False))
            self.rows.append(row)
            row.grid(i + 1)

    def active_files(self) -> list[tuple[str, str]]:
        return [r.values() for r in self.rows if r.is_active()]

    def dump(self) -> dict:
        return {"name": self.name, "rows": [r.data() for r in self.rows]}


# ---------------------------------------------------------------------------
class GravaBinApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} - Gravador ESP {APP_VERSION}")
        root.geometry("1000x780")
        root.minsize(820, 600)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: FlashWorker | None = None
        self.monitor: SerialMonitor | None = None
        self._reopen_monitor_after = False

        self._build_ui()
        self._refresh_ports()
        self.root.after(80, self._drain_log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        # Logo centralizado no espaço vazio à direita (canto superior direito).
        self._logo_img = self._load_logo(target=88)
        if self._logo_img is not None:
            top.columnconfigure(7, weight=1)
            ttk.Label(top, image=self._logo_img).grid(
                row=0, column=7, rowspan=3, sticky="", padx=(0, 8))

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
        ttk.Checkbutton(top, text="Verificar após gravar",
                        variable=self.var_verify).grid(row=2, column=5,
                                                       columnspan=2, sticky="w")

        box = ttk.LabelFrame(self.root, text="Presets de gravação", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Novo preset",
                   command=self.on_new_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Salvar preset",
                   command=self.on_save_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Excluir preset",
                   command=self.on_delete_preset).pack(side="left", padx=2)
        ttk.Label(bar, text="(duplo clique na aba para renomear)",
                  foreground="#888").pack(side="right")

        self.notebook = ttk.Notebook(box)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<Double-Button-1>", self._on_tab_double)

        self.panels: list[PresetPanel] = []
        self._load_presets()

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

        self.btn_monitor = ttk.Button(btns, text="Abrir monitor",
                                      command=self.on_toggle_monitor)
        self.btn_monitor.pack(side="left", padx=4)

        self.btn_clear = ttk.Button(btns, text="Limpar log",
                                    command=lambda: self.txt.delete("1.0", "end"))
        self.btn_clear.pack(side="right", padx=4)

        # Barra fina com as opções do monitor serial.
        mon_bar = ttk.Frame(self.root, padding=(10, 0))
        mon_bar.pack(fill="x")
        ttk.Label(mon_bar, text="Baud monitor:").pack(side="left", padx=(0, 2))
        self.cmb_mon_baud = ttk.Combobox(mon_bar, width=9, values=MONITOR_BAUDS,
                                         state="readonly")
        self.cmb_mon_baud.set("115200")
        self.cmb_mon_baud.pack(side="left")
        self.var_reopen_monitor = tk.BooleanVar(value=True)
        ttk.Checkbutton(mon_bar, text="Reabrir monitor após gravar/apagar",
                        variable=self.var_reopen_monitor).pack(side="left", padx=8)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(2, 4))

        # Status bar (fixada no rodapé antes do console, para nunca ser espremida)
        self.status = tk.StringVar(value="Pronto.")
        ttk.Label(self.root, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

        log_frame = ttk.LabelFrame(self.root, text="Console", padding=4)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.txt = tk.Text(log_frame, height=6, bg="#111", fg="#cfe",
                           insertbackground="#fff",
                           font=("DejaVu Sans Mono", 10), wrap="none")
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.config(yscrollcommand=sb.set)

    # ---------------- helpers ----------------
    def _load_logo(self, target: int = 88) -> "tk.PhotoImage | None":
        """Carrega o PNG do logo e ajusta para ~target px (canto da interface)."""
        path = _find_logo_png(target)
        if not path:
            return None
        try:
            img = tk.PhotoImage(file=path, master=self.root)
        except tk.TclError:
            return None
        w = img.width()
        if w <= 0 or w == target:
            return img
        # Tk só escala por fatores inteiros: aproxima target por zoom(a)/subsample(b).
        best = None
        for den in range(1, 9):
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
        # O monitor mantém a porta ocupada; fecha antes e, se pedido, reabre.
        self._reopen_monitor_after = bool(self.monitor and self.monitor.is_alive())
        if self._reopen_monitor_after:
            self._stop_monitor()
        self._set_busy(True)
        self.worker = FlashWorker(args, self.log_queue, self._on_done)
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_flash, self.btn_erase, self.btn_mac,
                  self.btn_monitor):
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
            if self._reopen_monitor_after and self.var_reopen_monitor.get():
                self._reopen_monitor_after = False
                # Pequena espera para o ESP terminar o reset pós-gravação.
                self.root.after(800, lambda: self._start_monitor(silent=True))
            else:
                self._reopen_monitor_after = False
        self.root.after(0, finish)

    # ---------------- monitor serial ----------------
    def on_toggle_monitor(self) -> None:
        if self.monitor and self.monitor.is_alive():
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self, silent: bool = False) -> bool:
        if serial is None:
            messagebox.showerror(APP_NAME,
                                 "Pacote 'pyserial' não encontrado.\n"
                                 "Instale com: pip install pyserial")
            return False
        if self.worker and self.worker.is_alive():
            if not silent:
                messagebox.showwarning(APP_NAME,
                                       "Aguarde a operação atual terminar.")
            return False
        if self.monitor and self.monitor.is_alive():
            return True
        port = self.cmb_port.get()
        if not port:
            messagebox.showwarning(APP_NAME, "Selecione uma porta serial.")
            return False
        try:
            baud = int(self.cmb_mon_baud.get())
        except ValueError:
            baud = 115200
        self.monitor = SerialMonitor(port, baud, self.log_queue,
                                     self._on_monitor_done)
        self.monitor.start()
        self.btn_monitor.configure(text="Fechar monitor")
        for b in (self.btn_flash, self.btn_erase, self.btn_mac):
            b.configure(state="disabled")
        self.status.set(f"Monitor serial em {port} @ {baud} bps.")
        return True

    def _stop_monitor(self) -> None:
        mon, self.monitor = self.monitor, None
        if mon is not None:
            mon.stop()
            mon.join(timeout=2)
        self.btn_monitor.configure(text="Abrir monitor")
        if not (self.worker and self.worker.is_alive()):
            for b in (self.btn_flash, self.btn_erase, self.btn_mac):
                b.configure(state="normal")
        self.status.set("Monitor serial fechado.")

    def _on_monitor_done(self, _ok: bool) -> None:
        self.root.after(0, self._monitor_finished)

    def _monitor_finished(self) -> None:
        # O monitor terminou por conta própria (ex.: dispositivo removido).
        if self.monitor is not None and not self.monitor.is_alive():
            self.monitor = None
            self.btn_monitor.configure(text="Abrir monitor")
            if not (self.worker and self.worker.is_alive()):
                for b in (self.btn_flash, self.btn_erase, self.btn_mac):
                    b.configure(state="normal")

    # ---------------- presets ----------------
    def _current_panel(self) -> PresetPanel | None:
        cur = self.notebook.select()
        for p in self.panels:
            if str(p) == cur:
                return p
        return None

    def _add_panel(self, name: str, rows_data: list[dict] | None,
                   save: bool = True, is_default: bool = False) -> PresetPanel:
        panel = PresetPanel(self.notebook, name, rows_data, is_default)
        self.panels.append(panel)
        self.notebook.add(panel, text=name)
        self.notebook.select(panel)
        if save:
            self._save_presets()
        return panel

    def _load_presets(self) -> None:
        data: list[dict] = []
        try:
            with open(PRESETS_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = []
        if not isinstance(data, list):
            data = []

        # Garante que a aba padrão exista sempre e fique em primeiro.
        default = next((p for p in data
                        if p.get("name") == DEFAULT_PRESET_NAME), None)
        if default is None:
            default = {"name": DEFAULT_PRESET_NAME, "rows": DEFAULT_ROWS_DATA}
        others = [p for p in data if p.get("name") != DEFAULT_PRESET_NAME]

        self._add_panel(DEFAULT_PRESET_NAME, default.get("rows"),
                        save=False, is_default=True)
        for preset in others:
            self._add_panel(preset.get("name", "Preset"),
                            preset.get("rows"), save=False)
        self.notebook.select(self.panels[0])

    def _save_presets(self) -> None:
        try:
            os.makedirs(os.path.dirname(PRESETS_PATH), exist_ok=True)
            with open(PRESETS_PATH, "w", encoding="utf-8") as fh:
                json.dump([p.dump() for p in self.panels], fh,
                          indent=2, ensure_ascii=False)
        except OSError as exc:
            self.status.set(f"Não foi possível salvar presets: {exc}")

    def on_new_preset(self) -> None:
        n = sum(1 for p in self.panels if not p.is_default) + 1
        self._add_panel(f"Preset {n}", None, save=False)
        self.status.set("Novo preset. Ajuste os arquivos e clique em "
                        "'Salvar preset'.")

    def on_save_preset(self) -> None:
        panel = self._current_panel()
        if panel is None:
            return
        if not panel.is_default:
            name = simpledialog.askstring(
                APP_NAME, "Nome do preset:", initialvalue=panel.name,
                parent=self.root)
            if not name or not name.strip():
                return
            panel.name = name.strip()
            self.notebook.tab(panel, text=panel.name)
        self._save_presets()
        self.status.set(f"Preset '{panel.name}' salvo.")

    def on_delete_preset(self) -> None:
        panel = self._current_panel()
        if panel is None:
            return
        if panel.is_default:
            messagebox.showinfo(APP_NAME,
                                "A aba padrão não pode ser removida.")
            return
        if not messagebox.askyesno(APP_NAME,
                                   f"Excluir o preset '{panel.name}'?"):
            return
        self.panels.remove(panel)
        self.notebook.forget(panel)
        self._save_presets()
        self.status.set("Preset excluído.")

    def _on_tab_double(self, event: tk.Event) -> None:
        try:
            idx = self.notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        self.notebook.select(idx)
        panel = self._current_panel()
        if panel is not None and not panel.is_default:
            self.on_save_preset()

    def _on_close(self) -> None:
        if self.monitor and self.monitor.is_alive():
            self._stop_monitor()
        self._save_presets()
        self.root.destroy()

    # ---------------- ações ----------------
    def on_flash(self) -> None:
        if not self._check_ready():
            return
        panel = self._current_panel()
        if panel is None:
            messagebox.showwarning(APP_NAME, "Crie um preset antes de gravar.")
            return
        files = panel.active_files()
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
def _logo_pngs() -> list[str]:
    """Lista os PNGs do logo disponíveis (fonte ou instalado), menor -> maior."""
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


def _find_logo_png(target: int) -> str | None:
    """PNG do logo mais próximo (>=) do tamanho pedido, senão o maior menor."""
    pngs = _logo_pngs()
    if not pngs:
        return None

    def size_of(path: str) -> int:
        digits = "".join(filter(str.isdigit, os.path.basename(path)))
        return int(digits) if digits else 0

    for p in pngs:
        if size_of(p) >= target:
            return p
    return pngs[-1]


def main() -> None:
    # className define o WM_CLASS da janela — deve casar com StartupWMClass no .desktop
    root = tk.Tk(className="Gravabin")
    icons = []
    for path in _logo_pngs():
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
    GravaBinApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
