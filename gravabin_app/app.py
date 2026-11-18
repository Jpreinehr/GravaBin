"""Modo de gravação única: monta a UI e liga os eventos aos workers."""

from __future__ import annotations

import collections
import queue
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import flashing, presets_store
from .constants import (
    APP_NAME,
    APP_VERSION,
    CONSOLE_MAX_LINES,
    DRAIN_BUDGET_S,
    MONITOR_BAUDS,
    MONITOR_LOG_MAX_CHUNKS,
    PRESET_EXT,
)
from .logo import LogoLabel
from .ports import list_serial_ports
from .widgets import FlashSettings, PresetPanel
from .workers import (
    Done,
    FlashWorker,
    MonitorText,
    SerialMonitor,
    esptool,
    sanitize_serial_text,
    serial,
)


class GravaBinApp:
    def __init__(self, root: tk.Tk, on_switch_mode=None) -> None:
        self.root = root
        self._on_switch_mode = on_switch_mode
        root.title(f"{APP_NAME} - Gravador ESP {APP_VERSION}")

        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: FlashWorker | None = None
        self.monitor: SerialMonitor | None = None
        self._reopen_monitor_after = False
        self._closed = False
        # Saída do monitor serial, guardada à parte do console para exportar.
        self._monitor_log: collections.deque[str] = collections.deque(
            maxlen=MONITOR_LOG_MAX_CHUNKS)
        # Aba cujas configurações estão nos campos (para salvá-las ao trocar).
        self._settings_panel: PresetPanel | None = None

        self._build_ui()
        self._refresh_ports()
        self.root.after(80, self._drain_log)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self.frame, padding=10)
        top.pack(fill="x")

        # Logo preenche o espaço livre à direita e acompanha o tamanho da janela.
        top.columnconfigure(4, weight=1)
        LogoLabel(top).grid(row=0, column=4, rowspan=2, sticky="nsew",
                            padx=(0, 8))

        # Linha 1: porta
        port_row = ttk.Frame(top)
        port_row.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(port_row, text="Porta:").pack(side="left", padx=(28, 0))
        self.cmb_port = ttk.Combobox(port_row, width=28, state="readonly")
        self.cmb_port.pack(side="left", padx=4, pady=4)
        ttk.Button(port_row, text="↻", width=3, command=self._refresh_ports
                   ).pack(side="left", padx=2)

        # Linhas 2-4: configurações de gravação (pertencem ao preset da aba).
        self.settings = FlashSettings(top)
        self.settings.grid(row=1, column=0, columnspan=4, sticky="w")

        box = ttk.LabelFrame(self.frame, text="Presets de gravação", padding=8)
        box.pack(fill="x", padx=10, pady=6)

        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Novo preset",
                   command=self.on_new_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Salvar preset",
                   command=self.on_save_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Excluir preset",
                   command=self.on_delete_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Exportar…",
                   command=self.on_export_preset).pack(side="left", padx=(12, 2))
        ttk.Button(bar, text="Importar…",
                   command=self.on_import_preset).pack(side="left", padx=2)
        ttk.Label(bar, text="(duplo clique na aba para renomear)",
                  foreground="#888").pack(side="right")

        self.notebook = ttk.Notebook(box)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<Double-Button-1>", self._on_tab_double)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.panels: list[PresetPanel] = []
        self._load_presets()

        btns = ttk.Frame(self.frame, padding=(10, 4))
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
                                    command=self._clear_log)
        self.btn_clear.pack(side="right", padx=4)

        if self._on_switch_mode is not None:
            ttk.Button(btns, text="Trocar modo",
                       command=self._on_switch_mode).pack(side="right", padx=4)

        # Barra fina com as opções do monitor serial.
        mon_bar = ttk.Frame(self.frame, padding=(10, 0))
        mon_bar.pack(fill="x")
        ttk.Label(mon_bar, text="Baud monitor:").pack(side="left", padx=(0, 2))
        self.cmb_mon_baud = ttk.Combobox(mon_bar, width=9, values=MONITOR_BAUDS,
                                         state="readonly")
        self.cmb_mon_baud.set("115200")
        self.cmb_mon_baud.pack(side="left")
        self.var_reopen_monitor = tk.BooleanVar(value=True)
        ttk.Checkbutton(mon_bar, text="Reabrir monitor após gravar/apagar",
                        variable=self.var_reopen_monitor).pack(side="left", padx=8)
        self.var_timestamps = tk.BooleanVar(value=True)
        ttk.Checkbutton(mon_bar, text="Data/hora nas linhas",
                        variable=self.var_timestamps,
                        command=self._on_toggle_timestamps
                        ).pack(side="left", padx=8)
        ttk.Button(mon_bar, text="Exportar log…",
                   command=self.on_export_monitor_log).pack(side="right", padx=4)

        self.progress = ttk.Progressbar(self.frame, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(2, 4))

        # Status bar (fixada no rodapé antes do console, para nunca ser espremida)
        self.status = tk.StringVar(value="Pronto.")
        ttk.Label(self.frame, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

        log_frame = ttk.LabelFrame(self.frame, text="Console", padding=4)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.txt = tk.Text(log_frame, height=6, bg="#111", fg="#cfe",
                           insertbackground="#fff",
                           font=("DejaVu Sans Mono", 10), wrap="none")
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.config(yscrollcommand=sb.set)

    # ---------------- helpers ----------------
    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.cmb_port["values"] = ports
        if ports and self.cmb_port.get() not in ports:
            self.cmb_port.set(ports[0])
        self.status.set(f"{len(ports)} porta(s) encontrada(s).")

    def _drain_log(self) -> None:
        if self._closed:
            return
        deadline = time.monotonic() + DRAIN_BUDGET_S
        appended = False
        try:
            while time.monotonic() < deadline:
                item = self.log_queue.get_nowait()
                if isinstance(item, Done):
                    # Só a thread principal (aqui) chama callbacks que tocam
                    # o Tkinter — nunca as threads de worker/monitor.
                    item.callback(item.ok)
                else:
                    if isinstance(item, MonitorText):
                        self._monitor_log.append(item)
                    self._append(item, see=False)
                    appended = True
        except queue.Empty:
            pass
        if appended:
            self._trim_console()
            self.txt.see("end")
        # Fila ainda cheia: volta logo; vazia: ritmo normal.
        self.root.after(10 if not self.log_queue.empty() else 80,
                        self._drain_log)

    def _append(self, text: str, see: bool = True) -> None:
        if text.startswith("\r"):
            # reescreve a última linha
            idx = self.txt.index("end-1c linestart")
            self.txt.delete(idx, "end-1c")
            self.txt.insert("end", text[1:])
        else:
            self.txt.insert("end", text)
        if see:
            self.txt.see("end")

    def _trim_console(self) -> None:
        extra = int(self.txt.index("end-1c").split(".")[0]) - CONSOLE_MAX_LINES
        if extra > 0:
            self.txt.delete("1.0", f"{extra + 1}.0")

    def _clear_log(self) -> None:
        self.txt.delete("1.0", "end")
        self._monitor_log.clear()

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
        return flashing.base_args(self.settings.get(), self.cmb_port.get())

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
        # Chamado pela thread principal a partir de _drain_log — seguro
        # tocar o Tkinter aqui diretamente.
        if self._closed:
            return
        self._set_busy(False)
        self.status.set("Concluído com sucesso." if ok else "Falhou. Veja o console.")
        if self._reopen_monitor_after and self.var_reopen_monitor.get():
            self._reopen_monitor_after = False
            # Pequena espera para o ESP terminar o reset pós-gravação.
            self.root.after(800, lambda: self._start_monitor(silent=True))
        else:
            self._reopen_monitor_after = False

    # ---------------- monitor serial ----------------
    def on_toggle_monitor(self) -> None:
        if self.monitor and self.monitor.is_alive():
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self, silent: bool = False) -> bool:
        if self._closed:
            return False
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
                                     self._on_monitor_done,
                                     timestamps=self.var_timestamps.get())
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

    def _on_toggle_timestamps(self) -> None:
        if self.monitor is not None:
            self.monitor.timestamps = self.var_timestamps.get()

    def on_export_monitor_log(self) -> None:
        text = sanitize_serial_text("".join(self._monitor_log))
        if not text.strip():
            messagebox.showinfo(APP_NAME, "O log do monitor serial está vazio.")
            return
        default = datetime.now().strftime("gravabin-monitor-%Y%m%d-%H%M%S.log")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Exportar log do monitor serial",
            initialfile=default, defaultextension=".log",
            filetypes=[("Log", "*.log"), ("Texto", "*.txt"),
                       ("Todos os arquivos", "*")])
        if not path:
            return
        try:
            # BOM: sem ele alguns editores confundem o log com UTF-16.
            with open(path, "w", encoding="utf-8-sig") as fh:
                fh.write(text.lstrip("\n"))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível salvar o log:\n{exc}")
            return
        self.status.set(f"Log do monitor exportado para {path}.")

    def _on_monitor_done(self, _ok: bool) -> None:
        # Chamado pela thread principal a partir de _drain_log — seguro
        # tocar o Tkinter aqui diretamente.
        if not self._closed:
            self._monitor_finished()

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

    def _on_tab_changed(self, _event=None) -> None:
        # As configurações exibidas pertencem à aba: guarda as da aba que
        # saiu e carrega as da que entrou (presets antigos herdam as atuais).
        if self._settings_panel in self.panels:
            self._settings_panel.settings = self.settings.get()
        panel = self._current_panel()
        if panel is not None and panel.settings:
            self.settings.set(panel.settings)
        self._settings_panel = panel

    def _add_panel(self, name: str, rows_data: list[dict] | None,
                   save: bool = True, is_default: bool = False,
                   settings: dict | None = None) -> PresetPanel:
        panel = PresetPanel(self.notebook, name, rows_data, is_default,
                            settings)
        self.panels.append(panel)
        self.notebook.add(panel, text=name)
        self.notebook.select(panel)
        if save:
            self._save_presets()
        return panel

    def _load_presets(self) -> None:
        default, others = presets_store.load_presets()
        # Garante que a aba padrão exista sempre e fique em primeiro.
        self._add_panel(default["name"], default.get("rows"),
                        save=False, is_default=True,
                        settings=presets_store.clean_settings(
                            default.get("settings")))
        for preset in others:
            self._add_panel(preset.get("name", "Preset"),
                            preset.get("rows"), save=False,
                            settings=presets_store.clean_settings(
                                preset.get("settings")))
        self.notebook.select(self.panels[0])
        self._on_tab_changed()

    def _save_presets(self) -> None:
        panel = self._current_panel()
        if panel is not None:
            panel.settings = self.settings.get()
        try:
            presets_store.save_presets([p.dump() for p in self.panels])
        except OSError as exc:
            self.status.set(f"Não foi possível salvar presets: {exc}")

    def on_new_preset(self) -> None:
        n = sum(1 for p in self.panels if not p.is_default) + 1
        self._add_panel(f"Preset {n}", None, save=False,
                        settings=self.settings.get())
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

    def on_export_preset(self) -> None:
        panel = self._current_panel()
        if panel is None:
            return
        panel.settings = self.settings.get()
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Exportar preset",
            initialfile=f"{panel.name}{PRESET_EXT}",
            defaultextension=PRESET_EXT,
            filetypes=[("Preset GravaBin", f"*{PRESET_EXT}"),
                       ("Todos os arquivos", "*")])
        if not path:
            return
        try:
            presets_store.export_preset(panel.dump(), path)
        except (presets_store.PresetError, OSError) as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível exportar:\n{exc}")
            return
        self.status.set(f"Preset '{panel.name}' exportado para {path}.")

    def on_import_preset(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="Importar preset",
            filetypes=[("Preset GravaBin", f"*{PRESET_EXT}"),
                       ("Todos os arquivos", "*")])
        if not path:
            return
        try:
            preset = presets_store.import_preset(
                path, {p.name for p in self.panels})
        except (presets_store.PresetError, OSError) as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível importar:\n{exc}")
            return
        self._add_panel(preset["name"], preset["rows"],
                        settings=preset.get("settings"))
        self._on_tab_changed()
        self.status.set(f"Preset '{preset['name']}' importado.")

    def _on_tab_double(self, event: tk.Event) -> None:
        try:
            idx = self.notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        self.notebook.select(idx)
        panel = self._current_panel()
        if panel is not None and not panel.is_default:
            self.on_save_preset()

    def close(self) -> bool:
        """Fecha esta tela (sair ou trocar de modo). False = usuário desistiu."""
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(APP_NAME,
                                   "Aguarde a operação atual terminar.")
            return False
        if self.monitor and self.monitor.is_alive():
            self._stop_monitor()
        self._save_presets()
        self._closed = True
        self.frame.destroy()
        return True

    # ---------------- ações ----------------
    def on_flash(self) -> None:
        if not self._check_ready():
            return
        panel = self._current_panel()
        if panel is None:
            messagebox.showwarning(APP_NAME, "Crie um preset antes de gravar.")
            return
        files = panel.active_files()
        error = flashing.validate_files(files)
        if error:
            messagebox.showwarning(APP_NAME, error)
            return
        self._start(flashing.write_flash_args(
            self.settings.get(), self.cmb_port.get(), files))

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
