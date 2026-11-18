"""Modo de gravação múltipla: o mesmo preset em várias portas ao mesmo tempo."""

from __future__ import annotations

import os
import queue
import time
import tkinter as tk
from functools import partial
from tkinter import messagebox, ttk

from . import flashing, presets_store
from .constants import (
    APP_NAME,
    APP_VERSION,
    CONSOLE_MAX_LINES,
    DRAIN_BUDGET_S,
)
from .logo import LogoLabel
from .ports import list_serial_ports
from .widgets import FlashSettings
from .workers import Done, PortLine, ProcessFlashWorker, esptool

# Cores do prefixo [porta] no console, uma por porta (ciclo).
_PORT_COLORS = ["#7fd4ff", "#ffd27f", "#b5ff7f", "#ff9fdc",
                "#9f9fff", "#7fffd4", "#ffb07f", "#d4d4d4"]


class PortRow:
    """Uma porta na lista: seleção, status e indicador de atividade."""

    def __init__(self, parent: tk.Widget, port: str, row: int,
                 checked: bool) -> None:
        self.port = port
        self.var = tk.BooleanVar(value=checked)
        self.chk = ttk.Checkbutton(parent, text=port, variable=self.var)
        self.chk.grid(row=row, column=0, sticky="w", padx=4, pady=1)
        self.status = ttk.Label(parent, text="—", width=60, anchor="w")
        self.status.grid(row=row, column=1, sticky="w", padx=4)
        self.bar = ttk.Progressbar(parent, mode="indeterminate", length=120)
        self.bar.grid(row=row, column=2, padx=4)

    def destroy(self) -> None:
        for w in (self.chk, self.status, self.bar):
            w.destroy()

    def set_running(self) -> None:
        self.status.configure(text="Iniciando…", foreground="")
        self.bar.start(10)

    def set_line(self, text: str) -> None:
        self.status.configure(text=text if len(text) <= 60
                              else text[:57] + "…")

    def set_result(self, ok: bool) -> None:
        self.bar.stop()
        if ok:
            self.status.configure(text="✔ Gravado com sucesso",
                                  foreground="#1a7f37")
        else:
            self.status.configure(text="✖ Falhou — veja o console",
                                  foreground="#c62828")


class MultiFlashScreen:
    def __init__(self, root: tk.Tk, on_switch_mode=None) -> None:
        self.root = root
        self._on_switch_mode = on_switch_mode
        root.title(f"{APP_NAME} - Gravação múltipla {APP_VERSION}")

        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)

        self.log_queue: queue.Queue = queue.Queue()
        self.workers: dict[str, ProcessFlashWorker] = {}
        self.results: dict[str, bool] = {}
        self.rows: dict[str, PortRow] = {}
        self._port_tags: dict[str, str] = {}
        self._closed = False

        default, others = presets_store.load_presets()
        self.presets = [default] + others

        self._build_ui()
        self._refresh_ports()
        self.root.after(80, self._drain_log)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self.frame, padding=10)
        top.pack(fill="x")
        top.columnconfigure(3, weight=1)

        LogoLabel(top).grid(row=0, column=3, rowspan=3, sticky="nsew",
                            padx=(0, 8))

        ttk.Label(top, text="Preset:").grid(row=0, column=0, sticky="e")
        self.cmb_preset = ttk.Combobox(
            top, width=30, state="readonly",
            values=[p.get("name", "Preset") for p in self.presets])
        self.cmb_preset.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.cmb_preset.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Label(top, text="(presets são editados no modo de gravação única)",
                  foreground="#888").grid(row=0, column=2, sticky="w")

        self.settings = FlashSettings(top)
        self.settings.grid(row=1, column=0, columnspan=3, sticky="w")

        self.lbl_files = ttk.Label(top, text="", foreground="#555",
                                   wraplength=640, justify="left")
        self.lbl_files.grid(row=2, column=0, columnspan=3, sticky="w",
                            pady=(2, 0))

        box = ttk.LabelFrame(self.frame, text="Portas", padding=8)
        box.pack(fill="x", padx=10, pady=6)
        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 4))
        self.btn_refresh = ttk.Button(bar, text="↻ Atualizar portas",
                                      command=self._refresh_ports)
        self.btn_refresh.pack(side="left", padx=2)
        self.btn_all = ttk.Button(bar, text="Marcar todas",
                                  command=lambda: self._check_all(True))
        self.btn_all.pack(side="left", padx=2)
        self.btn_none = ttk.Button(bar, text="Desmarcar todas",
                                   command=lambda: self._check_all(False))
        self.btn_none.pack(side="left", padx=2)
        self.ports_table = ttk.Frame(box)
        self.ports_table.pack(fill="x")

        btns = ttk.Frame(self.frame, padding=(10, 4))
        btns.pack(fill="x")
        self.btn_flash = ttk.Button(btns, text="Gravar selecionadas",
                                    command=self.on_flash)
        self.btn_flash.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(btns, text="Parar", state="disabled",
                                   command=self.on_stop)
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(btns, text="Limpar log",
                   command=lambda: self.txt.delete("1.0", "end")
                   ).pack(side="right", padx=4)
        if self._on_switch_mode is not None:
            self.btn_switch = ttk.Button(btns, text="Trocar modo",
                                         command=self._on_switch_mode)
            self.btn_switch.pack(side="right", padx=4)

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

        if self.presets:
            self.cmb_preset.current(0)
            self._on_preset_selected()

    # ---------------- preset ----------------
    def _selected_preset(self) -> dict | None:
        idx = self.cmb_preset.current()
        return self.presets[idx] if 0 <= idx < len(self.presets) else None

    def _preset_files(self) -> list[tuple[str, str]]:
        preset = self._selected_preset() or {}
        return [(str(r.get("offset", "")).strip(), str(r.get("path", "")).strip())
                for r in preset.get("rows") or []
                if r.get("use") and str(r.get("path", "")).strip()]

    def _on_preset_selected(self, _event=None) -> None:
        preset = self._selected_preset() or {}
        self.settings.set(presets_store.clean_settings(preset.get("settings")))
        files = self._preset_files()
        if files:
            desc = "   ".join(f"{off} {os.path.basename(p)}" for off, p in files)
            self.lbl_files.configure(text=f"Binários: {desc}")
        else:
            self.lbl_files.configure(
                text="Este preset não tem binários marcados.")

    # ---------------- portas ----------------
    def _refresh_ports(self) -> None:
        checked = {p for p, r in self.rows.items() if r.var.get()}
        for w in self.ports_table.winfo_children():
            w.destroy()
        self.rows.clear()
        ports = list_serial_ports()
        for i, port in enumerate(ports):
            self.rows[port] = PortRow(self.ports_table, port, i,
                                      port in checked)
        if not ports:
            ttk.Label(self.ports_table, text="Nenhuma porta encontrada.",
                      foreground="#888").grid(row=0, column=0, sticky="w",
                                              padx=4)
        self.status.set(f"{len(ports)} porta(s) encontrada(s).")

    def _check_all(self, value: bool) -> None:
        for r in self.rows.values():
            r.var.set(value)

    # ---------------- gravação ----------------
    def _running(self) -> bool:
        return any(w.is_alive() for w in self.workers.values())

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_flash, self.btn_refresh, self.btn_all,
                  self.btn_none):
            b.configure(state=state)
        if self._on_switch_mode is not None:
            self.btn_switch.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")
        self.cmb_preset.configure(state="disabled" if busy else "readonly")
        self.settings.set_state(not busy)
        for r in self.rows.values():
            r.chk.state(["disabled"] if busy else ["!disabled"])

    def on_flash(self) -> None:
        if esptool is None:
            messagebox.showerror(APP_NAME,
                                 "Pacote 'esptool' não encontrado.\n"
                                 "Instale com: pip install esptool")
            return
        if self._running():
            return
        ports = [p for p, r in self.rows.items() if r.var.get()]
        if not ports:
            messagebox.showwarning(APP_NAME, "Marque ao menos uma porta.")
            return
        files = self._preset_files()
        error = flashing.validate_files(files)
        if error:
            messagebox.showwarning(APP_NAME, error)
            return

        settings = self.settings.get()
        self.workers.clear()
        self.results.clear()
        for r in self.rows.values():
            if r.port not in ports:
                r.status.configure(text="—", foreground="")
        self._set_busy(True)
        for port in ports:
            self.rows[port].set_running()
            worker = ProcessFlashWorker(
                port, flashing.write_flash_args(settings, port, files),
                self.log_queue, partial(self._on_port_done, port))
            self.workers[port] = worker
            worker.start()
        self.status.set(f"Gravando {len(ports)} placa(s)…")

    def on_stop(self) -> None:
        for w in self.workers.values():
            w.stop()
        self.status.set("Cancelando…")

    def _on_port_done(self, port: str, ok: bool) -> None:
        # Chamado pela thread principal a partir de _drain_log.
        if self._closed:
            return
        self.results[port] = ok
        if port in self.rows:
            self.rows[port].set_result(ok)
        if len(self.results) < len(self.workers):
            done = len(self.results)
            self.status.set(f"{done}/{len(self.workers)} concluída(s)…")
            return
        self._set_busy(False)
        failed = sorted(p for p, ok in self.results.items() if not ok)
        total = len(self.results)
        if failed:
            self.status.set(f"{total - len(failed)}/{total} OK — falharam: "
                            + ", ".join(failed))
        else:
            self.status.set(f"Concluído: {total}/{total} gravada(s) com sucesso.")

    # ---------------- console ----------------
    def _tag_for(self, port: str) -> str:
        tag = self._port_tags.get(port)
        if tag is None:
            tag = f"port{len(self._port_tags)}"
            color = _PORT_COLORS[len(self._port_tags) % len(_PORT_COLORS)]
            self.txt.tag_configure(tag, foreground=color)
            self._port_tags[port] = tag
        return tag

    def _drain_log(self) -> None:
        if self._closed:
            return
        deadline = time.monotonic() + DRAIN_BUDGET_S
        appended = False
        last_line: dict[str, str] = {}
        try:
            while time.monotonic() < deadline:
                item = self.log_queue.get_nowait()
                if isinstance(item, Done):
                    item.callback(item.ok)
                elif isinstance(item, PortLine):
                    self.txt.insert("end", f"[{os.path.basename(item.port)}] ",
                                    self._tag_for(item.port))
                    self.txt.insert("end", item.text + "\n")
                    appended = True
                    last_line[item.port] = item.text
        except queue.Empty:
            pass
        # Uma atualização de status por porta por ciclo (a última linha basta).
        for port, text in last_line.items():
            row = self.rows.get(port)
            if row is not None and port not in self.results:
                row.set_line(text)
        if appended:
            extra = int(self.txt.index("end-1c").split(".")[0]) - CONSOLE_MAX_LINES
            if extra > 0:
                self.txt.delete("1.0", f"{extra + 1}.0")
            self.txt.see("end")
        self.root.after(10 if not self.log_queue.empty() else 80,
                        self._drain_log)

    def close(self) -> bool:
        """Fecha esta tela (sair ou trocar de modo). False = usuário desistiu."""
        if self._running():
            if not messagebox.askyesno(
                    APP_NAME, "Há gravações em andamento. Cancelar e sair?"):
                return False
            for w in self.workers.values():
                w.stop()
            for w in self.workers.values():
                w.join(timeout=3)
        self._closed = True
        self.frame.destroy()
        return True
