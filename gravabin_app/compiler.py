"""Modo compilador: compila e carrega sketches .ino, como o Arduino IDE 1.8.

O trabalho pesado fica com o arduino-cli (ver arduino.py); aqui só a tela,
o Gerenciador de Placas e o Gerenciador de Bibliotecas.
"""

from __future__ import annotations

import os
import queue
import subprocess
import time
import tkinter as tk
from functools import partial
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import arduino, presets_store
from .constants import APP_NAME, APP_VERSION, CONSOLE_MAX_LINES, DRAIN_BUDGET_S
from .logo import LogoLabel
from .ports import list_serial_ports
from .workers import BackgroundTask, Call, CommandWorker, Done

# Teclas que não alteram o texto do combo de placas (não refiltram a lista).
_NAV_KEYS = {"Up", "Down", "Left", "Right", "Return", "Escape", "Tab",
             "Home", "End", "Prior", "Next"}


# Mensagens fatais do esptool (o código de saída nem sempre as reflete).
_UPLOAD_FAILURES = ("A fatal esptool.py error occurred",
                    "A fatal error occurred")


def _open_external(path: str) -> None:
    try:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as exc:
        messagebox.showerror(APP_NAME, f"Não foi possível abrir:\n{exc}")


class CompilerScreen:
    def __init__(self, root: tk.Tk, on_switch_mode=None) -> None:
        self.root = root
        self._on_switch_mode = on_switch_mode
        root.title(f"{APP_NAME} - Compilador {APP_VERSION}")

        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)

        self.log_queue: queue.Queue = queue.Queue()
        self.worker: CommandWorker | None = None
        self._closed = False
        self.state = arduino.load_state()
        path = arduino.find_cli()
        self.cli = (arduino.ArduinoCli(path, self.state.get("extra_urls"))
                    if path else None)
        self._boards: dict[str, str] = {}      # texto do combo -> fqbn
        self._options: dict[str, tuple[ttk.Combobox, list[dict]]] = {}
        # (fqbn completo, sketch, build path) da última compilação OK.
        self._last_build: tuple[str, str, str] | None = None

        self._build_ui()
        self._refresh_ports()
        self.root.after(80, self._drain_log)
        if self.cli is None:
            self._set_busy(True)
            self.btn_stop.configure(state="disabled")
            self.status.set("arduino-cli não encontrado.")
            self._append("O arduino-cli não foi encontrado. Ele vem junto com o "
                         "pacote .deb do GravaBin;\nrodando do código-fonte, "
                         "instale-o no PATH ou coloque o binário em bin/.\n")
        else:
            self.load_boards()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self.frame, padding=10)
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, minsize=96)

        LogoLabel(top, max_size=96).grid(row=0, column=3, rowspan=2,
                                         sticky="nsew", padx=(8, 0))

        ttk.Label(top, text="Sketch:").grid(row=0, column=0, sticky="e")
        self.var_sketch = tk.StringVar(value=self.state.get("sketch", ""))
        ttk.Entry(top, textvariable=self.var_sketch, state="readonly"
                  ).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        sk_btns = ttk.Frame(top)
        sk_btns.grid(row=0, column=2, sticky="w")
        ttk.Button(sk_btns, text="Abrir…", command=self.on_open_sketch
                   ).pack(side="left", padx=2)
        ttk.Button(sk_btns, text="Editar", command=self.on_edit_sketch
                   ).pack(side="left", padx=2)
        ttk.Button(sk_btns, text="Pasta", command=self.on_open_folder
                   ).pack(side="left", padx=2)

        ttk.Label(top, text="Placa:").grid(row=1, column=0, sticky="e")
        self.cmb_board = ttk.Combobox(top)
        self.cmb_board.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self.cmb_board.bind("<<ComboboxSelected>>", self._on_board_selected)
        self.cmb_board.bind("<KeyRelease>", self._on_board_typed)
        port_box = ttk.Frame(top)
        port_box.grid(row=1, column=2, sticky="w")
        ttk.Label(port_box, text="Porta:").pack(side="left", padx=(4, 2))
        self.cmb_port = ttk.Combobox(port_box, width=16, state="readonly")
        self.cmb_port.pack(side="left")
        ttk.Button(port_box, text="↻", width=3, command=self._refresh_ports
                   ).pack(side="left", padx=2)

        self.opts_box = ttk.LabelFrame(
            self.frame, text="Opções da placa (menu Ferramentas)", padding=8)
        self.opts_box.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(self.opts_box, text="Selecione uma placa.",
                  foreground="#888").grid(row=0, column=0, sticky="w")

        btns = ttk.Frame(self.frame, padding=(10, 4))
        btns.pack(fill="x")
        self.btn_verify = ttk.Button(btns, text="✔ Verificar",
                                     command=self.on_verify)
        self.btn_verify.pack(side="left", padx=4)
        self.btn_upload = ttk.Button(btns, text="➜ Carregar",
                                     command=self.on_upload)
        self.btn_upload.pack(side="left", padx=4)
        self.btn_preset = ttk.Button(btns, text="Salvar como preset…",
                                     command=self.on_save_preset)
        self.btn_preset.pack(side="left", padx=4)
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

        bar2 = ttk.Frame(self.frame, padding=(10, 0))
        bar2.pack(fill="x")
        self.btn_boards = ttk.Button(bar2, text="Gerenciar placas…",
                                     command=self.on_board_manager)
        self.btn_boards.pack(side="left", padx=4)
        self.btn_libs = ttk.Button(bar2, text="Gerenciar bibliotecas…",
                                   command=self.on_library_manager)
        self.btn_libs.pack(side="left", padx=4)
        self.var_verbose = tk.BooleanVar(value=self.state.get("verbose", False))
        ttk.Checkbutton(bar2, text="Saída detalhada", variable=self.var_verbose
                        ).pack(side="left", padx=12)

        self.progress = ttk.Progressbar(self.frame, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(6, 4))

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
        self.txt.tag_configure("error", foreground="#ff8080")
        self.txt.tag_configure("title", foreground="#7fd4ff")

    # ---------------- console / fila ----------------
    def _drain_log(self) -> None:
        if self._closed:
            return
        deadline = time.monotonic() + DRAIN_BUDGET_S
        appended = False
        try:
            while time.monotonic() < deadline:
                item = self.log_queue.get_nowait()
                if isinstance(item, Done):
                    item.callback(item.ok)
                elif isinstance(item, Call):
                    if not self._closed:
                        item.run()
                else:
                    self._append(item, see=False)
                    appended = True
        except queue.Empty:
            pass
        if appended:
            extra = int(self.txt.index("end-1c").split(".")[0]) - CONSOLE_MAX_LINES
            if extra > 0:
                self.txt.delete("1.0", f"{extra + 1}.0")
            self.txt.see("end")
        self.root.after(10 if not self.log_queue.empty() else 80,
                        self._drain_log)

    def _append(self, text: str, tag: str | None = None,
                see: bool = True) -> None:
        if text.startswith("\r"):
            idx = self.txt.index("end-1c linestart")
            self.txt.delete(idx, "end-1c")
            text = text[1:]
        if tag is None and ("error:" in text or "Error" in text):
            tag = "error"
        self.txt.insert("end", text, tag)
        if see:
            self.txt.see("end")

    # ---------------- estado ----------------
    def _save_state(self) -> None:
        fqbn = self._board_fqbn()
        if fqbn:
            self.state["fqbn"] = fqbn
            self.state.setdefault("options", {})[fqbn] = self._selected_options()
        self.state["sketch"] = self.var_sketch.get()
        self.state["port"] = self.cmb_port.get()
        self.state["verbose"] = self.var_verbose.get()
        try:
            arduino.save_state(self.state)
        except OSError:
            pass

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for b in (self.btn_verify, self.btn_upload, self.btn_preset,
                  self.btn_boards, self.btn_libs):
            b.configure(state=state)
        if self._on_switch_mode is not None:
            self.btn_switch.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()

    def _busy(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _run(self, cmd: list[str], on_done, title: str,
             fail_markers: tuple[str, ...] = ()) -> bool:
        """Roda um comando longo do arduino-cli, com saída no console."""
        if self.cli is None:
            return False
        if self._busy():
            messagebox.showwarning(APP_NAME, "Aguarde a operação atual terminar.")
            return False
        self._append(f"\n=== {title} ===\n", "title")
        self.status.set(title + "…")
        self._set_busy(True)
        self.worker = CommandWorker(cmd, self.log_queue, on_done,
                                    env=self.cli.env,
                                    fail_markers=fail_markers)
        self.worker.start()
        return True

    def run_cli(self, args: list[str], title: str, then=None) -> bool:
        """Para os gerenciadores: roda `arduino-cli <args>` e chama then(ok)."""
        return self._run(self.cli.cmd(*args),
                         partial(self._on_cli_done, title, then), title)

    def _on_cli_done(self, title: str, then, ok: bool) -> None:
        if self._closed:
            return
        self._set_busy(False)
        self.status.set(f"{title}: {'concluído' if ok else 'falhou'}.")
        if then is not None:
            then(ok)

    def on_stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()

    # ---------------- sketch ----------------
    def on_open_sketch(self) -> None:
        current = self.var_sketch.get()
        initial = (arduino.sketch_dir(current) if current
                   else os.path.expanduser("~/Arduino"))
        path = filedialog.askopenfilename(
            parent=self.root, title="Abrir sketch",
            initialdir=initial if os.path.isdir(initial) else None,
            filetypes=[("Sketch Arduino", "*.ino"), ("Todos os arquivos", "*")])
        if not path:
            return
        problem = arduino.sketch_problem(path)
        if problem:
            messagebox.showwarning(APP_NAME, problem)
            return
        self.var_sketch.set(arduino.sketch_dir(path))
        self._last_build = None
        self._save_state()
        self.status.set(f"Sketch: {os.path.basename(self.var_sketch.get())}")

    def _main_ino(self) -> str | None:
        folder = self.var_sketch.get()
        if not folder:
            return None
        return os.path.join(folder, os.path.basename(folder) + ".ino")

    def on_edit_sketch(self) -> None:
        ino = self._main_ino()
        if ino and os.path.isfile(ino):
            _open_external(ino)
        else:
            messagebox.showinfo(APP_NAME, "Abra um sketch primeiro.")

    def on_open_folder(self) -> None:
        folder = self.var_sketch.get()
        if folder and os.path.isdir(folder):
            _open_external(folder)
        else:
            messagebox.showinfo(APP_NAME, "Abra um sketch primeiro.")

    # ---------------- placas e opções ----------------
    def load_boards(self) -> None:
        BackgroundTask(self.cli.list_boards, self.log_queue,
                       self._on_boards).start()

    def _on_boards(self, ok: bool, result) -> None:
        if not ok:
            self._append(f"[ERRO] ao listar placas: {result}\n", "error")
            return
        self._boards = {f"{name}  [{fqbn}]": fqbn for name, fqbn in result}
        self.cmb_board["values"] = list(self._boards)
        if not self._boards:
            self.status.set("Nenhuma placa instalada — use 'Gerenciar placas…' "
                            "para instalar ESP32/ESP8266.")
            return
        wanted = self.state.get("fqbn")
        current = self._board_fqbn() or wanted
        for text, fqbn in self._boards.items():
            if fqbn == current:
                self.cmb_board.set(text)
                self._on_board_selected()
                break

    def _board_fqbn(self) -> str | None:
        return self._boards.get(self.cmb_board.get())

    def _on_board_typed(self, event: tk.Event) -> None:
        if event.keysym in _NAV_KEYS:
            return
        typed = self.cmb_board.get().lower()
        self.cmb_board["values"] = [t for t in self._boards
                                    if typed in t.lower()] or list(self._boards)

    def _on_board_selected(self, _event=None) -> None:
        fqbn = self._board_fqbn()
        if not fqbn:
            return
        self.cmb_board["values"] = list(self._boards)
        self._last_build = None
        BackgroundTask(partial(self.cli.board_options, fqbn), self.log_queue,
                       partial(self._on_options, fqbn)).start()

    def _on_options(self, fqbn: str, ok: bool, result) -> None:
        if fqbn != self._board_fqbn():
            return  # o usuário já trocou de placa
        for w in self.opts_box.winfo_children():
            w.destroy()
        self._options.clear()
        if not ok:
            self._append(f"[ERRO] ao ler opções da placa: {result}\n", "error")
            return
        if not result:
            ttk.Label(self.opts_box, text="Esta placa não tem opções.",
                      foreground="#888").grid(row=0, column=0, sticky="w")
            return
        saved = (self.state.get("options") or {}).get(fqbn) or {}
        per_row = 3
        for i, opt in enumerate(result):
            values = opt.get("values") or []
            labels = [v.get("value_label", v.get("value", "")) for v in values]
            r, c = divmod(i, per_row)
            # Rótulos longos quebram linha para as 3 colunas caberem na janela.
            ttk.Label(self.opts_box, text=opt.get("option_label", "") + ":",
                      wraplength=150, justify="right"
                      ).grid(row=r, column=c * 2, sticky="e", padx=(8, 2),
                             pady=2)
            cmb = ttk.Combobox(self.opts_box, values=labels, state="readonly",
                               width=19)
            cmb.grid(row=r, column=c * 2 + 1, sticky="w", pady=2)
            chosen = next((j for j, v in enumerate(values)
                           if v.get("value") == saved.get(opt.get("option"))),
                          None)
            if chosen is None:
                chosen = next((j for j, v in enumerate(values)
                               if v.get("selected")), 0)
            if labels:
                cmb.current(chosen)
            cmb.bind("<<ComboboxSelected>>",
                     lambda _e: setattr(self, "_last_build", None))
            self._options[opt.get("option", "")] = (cmb, values)

    def _selected_options(self) -> dict[str, str]:
        out = {}
        for key, (cmb, values) in self._options.items():
            idx = cmb.current()
            if 0 <= idx < len(values):
                out[key] = values[idx].get("value", "")
        return out

    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.cmb_port["values"] = ports
        saved = self.state.get("port")
        if self.cmb_port.get() not in ports:
            self.cmb_port.set(saved if saved in ports
                              else (ports[0] if ports else ""))

    # ---------------- compilar / carregar ----------------
    def _check_sketch_and_board(self) -> tuple[str, str] | None:
        sketch = self.var_sketch.get()
        if not sketch:
            messagebox.showwarning(APP_NAME, "Abra um sketch (.ino) primeiro.")
            return None
        problem = arduino.sketch_problem(sketch)
        if problem:
            messagebox.showwarning(APP_NAME, problem)
            return None
        fqbn = self._board_fqbn()
        if not fqbn:
            messagebox.showwarning(APP_NAME, "Selecione uma placa.")
            return None
        return sketch, arduino.full_fqbn(fqbn, self._selected_options())

    def _compile(self, then=None) -> None:
        checked = self._check_sketch_and_board()
        if checked is None:
            return
        sketch, fqbn = checked
        self._save_state()
        build_path = arduino.build_path_for(sketch)
        self._run(self.cli.compile_cmd(fqbn, sketch, build_path,
                                       self.var_verbose.get()),
                  partial(self._on_compiled, then, fqbn, sketch, build_path),
                  f"Compilando {os.path.basename(sketch)} ({fqbn})")

    def _on_compiled(self, then, fqbn: str, sketch: str, build_path: str,
                     ok: bool) -> None:
        if self._closed:
            return
        self._set_busy(False)
        if not ok:
            self._last_build = None
            self.status.set("Erro de compilação. Veja o console.")
            return
        self._last_build = (fqbn, sketch, build_path)
        self.status.set("Compilação concluída.")
        if then is not None:
            then()

    def on_verify(self) -> None:
        self._compile()

    def on_upload(self) -> None:
        if not self.cmb_port.get():
            messagebox.showwarning(APP_NAME, "Selecione uma porta serial.")
            return
        self._compile(then=self._upload)

    def _upload(self) -> None:
        fqbn, sketch, build_path = self._last_build
        port = self.cmb_port.get()
        self._run(self.cli.upload_cmd(fqbn, sketch, build_path, port,
                                      self.var_verbose.get()),
                  self._on_uploaded, f"Carregando em {port}",
                  # O upload.py do core ESP8266 pode sair com 0 após erro.
                  fail_markers=_UPLOAD_FAILURES)

    def _on_uploaded(self, ok: bool) -> None:
        if self._closed:
            return
        self._set_busy(False)
        self.status.set("Carregado com sucesso." if ok
                        else "Falha ao carregar. Veja o console.")

    def on_save_preset(self) -> None:
        checked = self._check_sketch_and_board()
        if checked is None:
            return
        sketch, fqbn = checked
        if self._last_build is None or self._last_build[:2] != (fqbn, sketch):
            messagebox.showinfo(APP_NAME, "Compile o sketch (Verificar) com a "
                                          "placa e opções atuais antes de "
                                          "salvar como preset.")
            return
        name = simpledialog.askstring(
            APP_NAME, "Nome do preset:", parent=self.root,
            initialvalue=os.path.basename(sketch))
        if not name or not name.strip():
            return
        build_path = self._last_build[2]

        def task() -> tuple[str, list[tuple[str, str]]]:
            props = self.cli.build_properties(fqbn, sketch)
            images = arduino.built_images(build_path, props)
            final = presets_store.add_built_preset(
                name.strip(), images, arduino.settings_from_props(props))
            return final, images

        self.status.set("Criando preset…")
        BackgroundTask(task, self.log_queue, self._on_preset_saved).start()

    def _on_preset_saved(self, ok: bool, result) -> None:
        if not ok:
            self.status.set("Não foi possível criar o preset.")
            messagebox.showerror(APP_NAME, f"Não foi possível criar o preset:\n"
                                           f"{result}")
            return
        name, images = result
        files = "\n".join(f"  {off}  {os.path.basename(p)}" for off, p in images)
        self.status.set(f"Preset '{name}' criado.")
        messagebox.showinfo(APP_NAME, f"Preset '{name}' criado com:\n{files}\n\n"
                                      "Ele já aparece nos modos de gravação "
                                      "única e múltipla.")

    # ---------------- gerenciadores ----------------
    def on_board_manager(self) -> None:
        BoardManager(self)

    def on_library_manager(self) -> None:
        LibraryManager(self)

    def close(self) -> bool:
        """Fecha esta tela (sair ou trocar de modo). False = usuário desistiu."""
        if self._busy():
            if not messagebox.askyesno(
                    APP_NAME, "Há uma operação em andamento. Cancelar e sair?"):
                return False
            self.worker.stop()
            self.worker.join(timeout=3)
        if self.cli is not None:
            self._save_state()
        self._closed = True
        self.frame.destroy()
        return True


# ---------------------------------------------------------------------------
class _ManagerDialog(tk.Toplevel):
    """Base dos gerenciadores: janela filha da tela, com saída no console."""

    def __init__(self, screen: CompilerScreen, title: str) -> None:
        super().__init__(screen.frame)
        self.screen = screen
        self.cli = screen.cli
        self.title(title)
        self.geometry("820x460")
        self.transient(screen.root)
        self.status = tk.StringVar(value="Carregando…")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken"
                  ).pack(fill="x", side="bottom")

    def _tree(self, parent: tk.Widget, columns: list[tuple[str, str, int]]
              ) -> ttk.Treeview:
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True, pady=4)
        tree = ttk.Treeview(box, columns=[c[0] for c in columns],
                            show="headings", selectmode="browse")
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, stretch=key == columns[-1][0])
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)
        return tree

    def _run(self, args: list[str], title: str, then) -> None:
        if self.screen.run_cli(args, title, then=self._guard(then)):
            self.status.set(f"{title}… (andamento no console)")

    def _guard(self, fn):
        """Ignora o callback se a janela já tiver sido fechada."""
        def wrapper(*args):
            if self.winfo_exists():
                fn(*args)
        return wrapper

    def _task(self, fn, callback) -> None:
        BackgroundTask(fn, self.screen.log_queue,
                       self._guard(callback)).start()


class BoardManager(_ManagerDialog):
    def __init__(self, screen: CompilerScreen) -> None:
        super().__init__(screen, "Gerenciador de placas")
        self._platforms: list[dict] = []
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)

        bar = ttk.Frame(body)
        bar.pack(fill="x")
        ttk.Label(bar, text="Filtrar:").pack(side="left")
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add("write", lambda *_: self._fill())
        ttk.Entry(bar, textvariable=self.var_filter, width=30
                  ).pack(side="left", padx=4)
        ttk.Button(bar, text="URLs adicionais…", command=self.on_urls
                   ).pack(side="right", padx=2)
        ttk.Button(bar, text="Atualizar índices", command=self.update_index
                   ).pack(side="right", padx=2)

        self.tree = self._tree(body, [("id", "ID", 170), ("name", "Nome", 220),
                                      ("installed", "Instalada", 110),
                                      ("latest", "Mais recente", 110),
                                      ("maintainer", "Mantenedor", 160)])
        acts = ttk.Frame(body)
        acts.pack(fill="x")
        ttk.Button(acts, text="Instalar / Atualizar", command=self.on_install
                   ).pack(side="left", padx=2)
        ttk.Button(acts, text="Remover", command=self.on_remove
                   ).pack(side="left", padx=2)
        ttk.Label(acts, text="O ESP32 baixa ~1 GB de ferramentas na primeira "
                             "instalação.", foreground="#888"
                  ).pack(side="right")
        self.update_index()

    def update_index(self) -> None:
        self._run(["core", "update-index"], "Atualizando índices de placas",
                  lambda _ok: self.reload())

    def reload(self) -> None:
        self.status.set("Carregando plataformas…")
        self._task(self.cli.platforms, self._on_platforms)

    def _on_platforms(self, ok: bool, result) -> None:
        if not ok:
            self.status.set(f"Erro: {result}")
            return
        self._platforms = result
        self._fill()
        n = sum(1 for p in result if p["installed"])
        self.status.set(f"{len(result)} plataformas, {n} instalada(s).")

    def _fill(self) -> None:
        typed = self.var_filter.get().lower()
        self.tree.delete(*self.tree.get_children())
        for p in self._platforms:
            if typed and typed not in (p["id"] + p["name"]).lower():
                continue
            self.tree.insert("", "end", iid=p["id"], values=(
                p["id"], p["name"], p["installed"] or "—", p["latest"],
                p["maintainer"]))

    def _selected(self) -> dict | None:
        sel = self.tree.selection()
        return next((p for p in self._platforms if sel and p["id"] == sel[0]),
                    None)

    def _after_change(self, _ok: bool) -> None:
        self.reload()
        self.screen.load_boards()

    def on_install(self) -> None:
        p = self._selected()
        if p is None:
            return
        if p["installed"] and p["installed"] == p["latest"]:
            self.status.set(f"{p['id']} já está na versão mais recente.")
            return
        verb = "upgrade" if p["installed"] else "install"
        self._run(["core", verb, p["id"]], f"Instalando {p['id']}",
                  self._after_change)

    def on_remove(self) -> None:
        p = self._selected()
        if p is None or not p["installed"]:
            return
        if messagebox.askyesno(APP_NAME, f"Remover {p['id']}?", parent=self):
            self._run(["core", "uninstall", p["id"]], f"Removendo {p['id']}",
                      self._after_change)

    def on_urls(self) -> None:
        current = ", ".join(self.screen.state.get("extra_urls") or [])
        text = simpledialog.askstring(
            APP_NAME, "URLs adicionais de placas (separadas por vírgula).\n"
                      "ESP32, ESP8266 e as do Arduino IDE já são usadas.",
            initialvalue=current, parent=self)
        if text is None:
            return
        urls = [u.strip() for u in text.split(",") if u.strip()]
        self.screen.state["extra_urls"] = urls
        self.cli.extra_urls = urls
        try:
            arduino.save_state(self.screen.state)
        except OSError:
            pass
        self.update_index()


class LibraryManager(_ManagerDialog):
    def __init__(self, screen: CompilerScreen) -> None:
        super().__init__(screen, "Gerenciador de bibliotecas")
        self._found: list[dict] = []
        self._installed: list[dict] = []
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # Aba: buscar
        search = ttk.Frame(nb, padding=6)
        nb.add(search, text="Buscar")
        bar = ttk.Frame(search)
        bar.pack(fill="x")
        ttk.Label(bar, text="Buscar:").pack(side="left")
        self.var_query = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.var_query, width=36)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda _e: self.on_search())
        ttk.Button(bar, text="Buscar", command=self.on_search
                   ).pack(side="left")
        ttk.Button(bar, text="Instalar .zip…", command=self.on_install_zip
                   ).pack(side="right")
        self.tree_found = self._tree(search, [
            ("name", "Nome", 200), ("version", "Versão", 80),
            ("author", "Autor", 160), ("sentence", "Descrição", 300)])
        self.tree_found.bind("<<TreeviewSelect>>", self._on_found_selected)
        acts = ttk.Frame(search)
        acts.pack(fill="x")
        ttk.Label(acts, text="Versão:").pack(side="left")
        self.cmb_version = ttk.Combobox(acts, width=12, state="readonly")
        self.cmb_version.pack(side="left", padx=4)
        ttk.Button(acts, text="Instalar", command=self.on_install
                   ).pack(side="left", padx=2)

        # Aba: instaladas
        inst = ttk.Frame(nb, padding=6)
        nb.add(inst, text="Instaladas")
        self.tree_inst = self._tree(inst, [
            ("name", "Nome", 220), ("version", "Instalada", 90),
            ("latest", "Disponível", 90), ("sentence", "Descrição", 340)])
        acts2 = ttk.Frame(inst)
        acts2.pack(fill="x")
        ttk.Button(acts2, text="Atualizar", command=self.on_upgrade
                   ).pack(side="left", padx=2)
        ttk.Button(acts2, text="Remover", command=self.on_remove
                   ).pack(side="left", padx=2)
        ttk.Label(acts2, text="Bibliotecas do sketchbook (~/Arduino/libraries),"
                              " compartilhadas com o Arduino IDE.",
                  foreground="#888").pack(side="right")

        ent.focus_set()
        self._run(["lib", "update-index"], "Atualizando índice de bibliotecas",
                  lambda _ok: self.reload_installed())

    # ---- buscar ----
    def on_search(self) -> None:
        query = self.var_query.get().strip()
        if not query:
            return
        self.status.set(f"Buscando '{query}'…")
        self._task(partial(self.cli.search_libraries, query), self._on_found)

    def _on_found(self, ok: bool, result) -> None:
        if not ok:
            self.status.set(f"Erro: {result}")
            return
        self._found = result
        self.tree_found.delete(*self.tree_found.get_children())
        for i, lib in enumerate(result):
            self.tree_found.insert("", "end", iid=str(i), values=(
                lib["name"], lib["version"], lib["author"], lib["sentence"]))
        self.status.set(f"{len(result)} biblioteca(s) encontrada(s).")

    def _on_found_selected(self, _event=None) -> None:
        sel = self.tree_found.selection()
        if not sel:
            return
        lib = self._found[int(sel[0])]
        versions = list(reversed(lib["versions"])) or [lib["version"]]
        self.cmb_version["values"] = versions
        self.cmb_version.set(versions[0])

    def on_install(self) -> None:
        sel = self.tree_found.selection()
        if not sel:
            return
        lib = self._found[int(sel[0])]
        version = self.cmb_version.get()
        spec = f"{lib['name']}@{version}" if version else lib["name"]
        self._run(["lib", "install", spec], f"Instalando {spec}",
                  lambda _ok: self.reload_installed())

    def on_install_zip(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Instalar biblioteca .zip",
            filetypes=[("Biblioteca .zip", "*.zip")])
        if path:
            self._run(["lib", "install", "--zip-path", path],
                      f"Instalando {os.path.basename(path)}",
                      lambda _ok: self.reload_installed())

    # ---- instaladas ----
    def reload_installed(self) -> None:
        self._task(self.cli.installed_libraries, self._on_installed)

    def _on_installed(self, ok: bool, result) -> None:
        if not ok:
            self.status.set(f"Erro: {result}")
            return
        self._installed = result
        self.tree_inst.delete(*self.tree_inst.get_children())
        for i, lib in enumerate(result):
            newer = lib["latest"] if lib["latest"] != lib["version"] else ""
            self.tree_inst.insert("", "end", iid=str(i), values=(
                lib["name"], lib["version"], newer, lib["sentence"]))
        self.status.set(f"{len(result)} biblioteca(s) instalada(s).")

    def _selected_installed(self) -> dict | None:
        sel = self.tree_inst.selection()
        return self._installed[int(sel[0])] if sel else None

    def on_upgrade(self) -> None:
        lib = self._selected_installed()
        if lib is not None:
            self._run(["lib", "upgrade", lib["name"]],
                      f"Atualizando {lib['name']}",
                      lambda _ok: self.reload_installed())

    def on_remove(self) -> None:
        lib = self._selected_installed()
        if lib is not None and messagebox.askyesno(
                APP_NAME, f"Remover a biblioteca {lib['name']}?", parent=self):
            self._run(["lib", "uninstall", lib["name"]],
                      f"Removendo {lib['name']}",
                      lambda _ok: self.reload_installed())
