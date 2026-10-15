"""gui.app — 两页界面

    第 1 页「运行」   左：步骤列表（状态）      右：输出日志（顶端显示当前节点）
    第 2 页「节点代码」左：步骤列表（可点击）    右：该步骤的代码（可改、可存）

两页的左列都是 **视口宽度的 1/5**（grid weight 1:4），比例不严格 ——
按操作习惯定的。

线程模型（tkinter 不是线程安全的，这条不能破）：

    主线程   : 所有 widget 操作、after() 轮询队列
    worker 线程: 子进程 stdout 读取 + state.json 轮询
    ------------- 两者之间只有 queue.Queue -------------

**任何 worker 都不碰 widget。** 这是旧骨架（[orchestrator/gui.py:11]
(../orchestrator/gui.py#L11)）已经验证过的边界，这里沿用。
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

from . import chain
from .editor import CodeEditor
from .runner import Runner, StateWatcher, discover_run_dir_from_line

# 配色：与旧骨架一致（已肉眼复核过观感，见 GUI-SKELETON-VERIFICATION.md §4）
BG = "#f5f5f5"
LOG_BG = "#1e1e1e"
LOG_FG = "#d4d4d4"
TAGS = {
    "node":  "#569cd6",
    "ok":    "#4ec9b0",
    "warn":  "#dcdcaa",
    "err":   "#f48771",
    "cmd":   "#808080",
    "plain": "#d4d4d4",
}

NODE_STYLE = {
    "ok":      ("\u2714", "#2e7d32", "#ffffff", "已完成"),
    "failed":  ("\u2716", "#c62828", "#ffffff", "失败"),
    "timeout": ("\u23f1", "#ef6c00", "#ffffff", "超时"),
    "skipped": ("\u2013", "#9e9e9e", "#ffffff", "跳过"),
    "running": ("\u25b6", "#1565c0", "#e3f2fd", "运行中"),
    None:      ("\u25cb", "#9e9e9e", "#ffffff", "未运行"),
}

# 目标程序下拉项。中文在前（人读），--target 的取值在括号里（机读）。
# ⚠️ 与 gui/chain.py 同样的理由：这里**独立声明**，不 import orchestrator，
# 否则 main.py 一坏，GUI 连修它的界面都打不开。
TARGET_CHOICES = [
    "跟随记录（默认）",
    "ok-ww",
    "ok-nte",
    "两个都跑（先 ok-ww 后 ok-nte）",
]
# 显示文本 -> --target 取值。None = 不传该参数。
TARGET_ARG = {
    "跟随记录（默认）": None,
    "ok-ww": "ww",
    "ok-nte": "nte",
    "两个都跑（先 ok-ww 后 ok-nte）": "both",
}


class Bus:
    """worker -> 主线程的唯一通道。只放数据，不放 widget 操作。"""

    def __init__(self):
        self.q = queue.Queue()

    def log(self, msg, kind=None):
        self.q.put(("log", (msg, kind)))

    def node(self, sid, name, status, note=None, elapsed=None):
        self.q.put(("node", (sid, name, status, note, elapsed)))

    def finished(self, code, note):
        self.q.put(("finished", (code, note)))

    def status(self, text, level="info"):
        self.q.put(("status", (text, level)))


class App(tk.Tk):
    def __init__(self, dry_run=False, only=None):
        super().__init__()
        self.title("ok-ww 断点式编排 — GUI")
        self.geometry("1280x780")
        self.minsize(1000, 620)

        self.bus = Bus()
        self.runner = Runner(self.bus)
        self.watcher = StateWatcher(self.bus, chain.latest_run_dir())
        self.worker = None
        self.run_dir = None
        self.result = None

        self.dry_run = tk.BooleanVar(value=dry_run)
        self.only_var = tk.StringVar(value=only or "")
        self.resume_var = tk.BooleanVar(value=False)
        # 目标程序："" = 跟随 state.json；"both" = 两程序串联
        self.target_var = tk.StringVar(value=TARGET_CHOICES[0])
        self.python_var = tk.StringVar(value=sys.executable)

        self.node_rows = {}      # 第 1 页的步骤行
        self.pick_rows = {}      # 第 2 页的步骤行
        self.selected = None

        self._build_style()
        self._build_banner()
        self._build_body()
        self._build_statusbar()
        self._check_chain()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self._pump)

    # ------------------------------------------------------------- 外观

    def _build_style(self):
        for theme in ("vista", "winnative", "clam"):
            try:
                ttk.Style().theme_use(theme)
                break
            except tk.TclError:
                continue
        self.configure(bg=BG)
        base = ("Microsoft YaHei UI", 9)
        self.option_add("*Font", base)

    def _build_banner(self):
        """未提权横幅：常驻（不是点运行时才弹）。

        "未提权 = 节点 9 无法终止 ok-ww" 是**持续状态**，不是瞬时事件，
        所以常驻。对应选型文档 §6 的 Q10 降级路径 (b)。
        """
        self.banner = tk.Frame(self, bg="#c62828")
        self.banner_label = tk.Label(
            self.banner, bg="#c62828", fg="white", anchor="w", justify="left",
            font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=5)
        self.banner_label.pack(fill="x")
        if not self._is_admin():
            self.banner_label.config(
                text="\u26a0 未提权运行 — 节点 1 将按参数跳过，节点 9 无法终止 "
                     "ok-ww 进程；超时/失败后需手动清理。")
            self.banner.pack(fill="x", side="top")

    @staticmethod
    def _is_admin():
        """只读本进程令牌判断提权 —— 不 import orchestrator，避免耦合。"""
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    # ------------------------------------------------------------- 主体

    def _build_body(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        self.page_run = ttk.Frame(self.nb)
        self.page_code = ttk.Frame(self.nb)
        self.nb.add(self.page_run, text="  运行  ")
        self.nb.add(self.page_code, text="  节点代码  ")

        self._build_page_run(self.page_run)
        self._build_page_code(self.page_code)

    # --- 第 1 页 ------------------------------------------------------

    def _build_page_run(self, page):
        page.columnconfigure(0, weight=1, minsize=200)   # 1/5
        page.columnconfigure(1, weight=4)
        page.rowconfigure(0, weight=1)

        # 左：步骤列表
        left = ttk.Labelframe(page, text="步骤", padding=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)

        self.run_list = tk.Frame(left, bg="#ffffff")
        self.run_list.pack(fill="both", expand=True)
        for sid, name, _mod, _why, _a in chain.STEPS:
            self.node_rows[sid] = self._make_row(
                self.run_list, sid, name, on_click=None)

        # 右：日志
        right = ttk.Labelframe(page, text="输出日志", padding=4)
        right.grid(row=0, column=1, sticky="nsew", pady=6)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # 日志**顶端**的当前节点指示
        head = tk.Frame(right, bg="#e8eef7")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.lbl_current = tk.Label(
            head, text="当前步骤 —  尚未开始", bg="#e8eef7", fg="#33475b",
            anchor="w", font=("Microsoft YaHei UI", 10, "bold"),
            padx=8, pady=5)
        self.lbl_current.pack(fill="x")

        wrap = tk.Frame(right)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.log_text = tk.Text(
            wrap, wrap="none", font=("Consolas", 9),
            bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            selectbackground="#264f78", padx=6, pady=4)
        self.log_text.pack(side="left", fill="both", expand=True)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.log_text.yview)
        vs.pack(side="right", fill="y")
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=self.log_text.xview)
        hs.pack(side="bottom", fill="x")
        self.log_text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        for tag, color in TAGS.items():
            self.log_text.tag_configure(tag, foreground=color)
        self.log_text.tag_configure("node",
                                    foreground=TAGS["node"],
                                    font=("Consolas", 9, "bold"))

        # 控制条（放在日志下方，靠近日志更顺手）
        ctl = ttk.Frame(page)
        ctl.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.btn_run = ttk.Button(ctl, text="\u25b6 运行编排", command=self.on_run)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(ctl, text="\u25a0 停止", command=self.on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=(6, 0))
        ttk.Separator(ctl, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Checkbutton(ctl, text="dry-run", variable=self.dry_run).pack(side="left")
        ttk.Separator(ctl, orient="vertical").pack(side="left", fill="y", padx=10)
        # 目标程序选择器。"" 表示不传 --target（跟随 state.json 的记录，
        # 这样 `接着上次` 不会把 ok-nte 的运行悄悄改回 ok-ww）。
        ttk.Label(ctl, text="目标").pack(side="left")
        ttk.Combobox(ctl, textvariable=self.target_var, width=14, state="readonly",
                     values=TARGET_CHOICES).pack(side="left", padx=(4, 0))
        ttk.Label(ctl, text="只跑节点").pack(side="left", padx=(12, 2))
        ttk.Combobox(ctl, textvariable=self.only_var, width=4, state="readonly",
                     values=[""] + chain.STEP_IDS).pack(side="left")
        ttk.Checkbutton(ctl, text="接着上次", variable=self.resume_var).pack(
            side="left", padx=(12, 0))

    # --- 第 2 页 ------------------------------------------------------

    def _build_page_code(self, page):
        page.columnconfigure(0, weight=1, minsize=200)   # 1/5，与第 1 页一致
        page.columnconfigure(1, weight=4)
        page.rowconfigure(0, weight=1)

        left = ttk.Labelframe(page, text="步骤", padding=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)
        self.pick_list = tk.Frame(left, bg="#ffffff")
        self.pick_list.pack(fill="both", expand=True)
        for sid, name, _mod, _why, _a in chain.STEPS:
            self.pick_rows[sid] = self._make_row(
                self.pick_list, sid, name, on_click=self.on_pick)

        right = ttk.Frame(page)
        right.grid(row=0, column=1, sticky="nsew", pady=6)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.editor = CodeEditor(right)
        self.editor.grid(row=0, column=0, sticky="nsew")

        # 右下角：保存
        foot = ttk.Frame(right)
        foot.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.lbl_file = ttk.Label(foot, text="（未选择步骤）", foreground="#555")
        self.lbl_file.pack(side="left")
        self.btn_save = ttk.Button(foot, text="保存", command=self.on_save,
                                   state="disabled")
        self.btn_save.pack(side="right")               # 右下角
        self.btn_revert = ttk.Button(foot, text="放弃修改", command=self.on_revert,
                                     state="disabled")
        self.btn_revert.pack(side="right", padx=(0, 6))

        self.bind_all("<Control-s>", self._ctrl_s)

    def _ctrl_s(self, _event=None):
        if self.nb.index(self.nb.select()) == 1 and self.selected:
            self.on_save()
            return "break"
        return None

    # --- 步骤行的构造 --------------------------------------------------

    def _make_row(self, parent, sid, name, on_click=None):
        """一行：序号（等宽，像代码行号）+ 名称 + 状态点。"""
        row = tk.Frame(parent, bg="#ffffff", bd=0, highlightthickness=0)
        row.pack(fill="x", pady=1)

        num = tk.Label(row, text=f"{sid:>2}", width=3, bg="#f0f0f0",
                       fg="#7a7a7a", font=("Consolas", 10, "bold"))
        num.pack(side="left", fill="y")

        body = tk.Frame(row, bg="#ffffff")
        body.pack(side="left", fill="x", expand=True, padx=(6, 2))
        title = tk.Label(body, text=name, bg="#ffffff", anchor="w",
                         font=("Microsoft YaHei UI", 9, "bold"))
        title.pack(fill="x")
        sub = tk.Label(body, text="", bg="#ffffff", anchor="w", fg="#8a8a8a",
                       font=("Microsoft YaHei UI", 8))
        sub.pack(fill="x")

        dot = tk.Label(row, text="\u25cb", width=2, bg="#ffffff", fg="#9e9e9e",
                       font=("Segoe UI", 10))
        dot.pack(side="right")

        info = {"frame": row, "num": num, "body": body, "title": title,
                "sub": sub, "dot": dot}

        if on_click:
            for w in (row, num, body, title, sub, dot):
                w.bind("<Button-1>", lambda e, s=sid: on_click(s))
                w.configure(cursor="hand2")

        return info

    def _paint(self, info, status, note=None, selected=False):
        mark, fg, bg, label = NODE_STYLE.get(status, NODE_STYLE[None])
        if selected:
            bg = "#dbeafe" if status != "running" else "#e3f2fd"
        info["dot"].config(text=mark, fg=fg)
        info["frame"].config(bg=bg)
        info["body"].config(bg=bg)
        info["title"].config(bg=bg)
        info["sub"].config(bg=bg, text=note if note is not None else label)
        info["num"].config(bg="#e4e4e4" if not selected else "#c7ddf5")

    # ------------------------------------------------------------- 第 1 页

    def append_log(self, msg, kind=None):
        if kind is None:
            s = msg.strip()
            if s.startswith("[节点") or s.startswith("[主控]"):
                kind = "node"
            elif "[OK]" in s or s.startswith("[结果]"):
                kind = "ok"
            elif "[警告]" in s or "[!!]" in s or "跳过" in s:
                kind = "warn"
            elif "[中止]" in s or "[异常]" in s or "FAILED" in s or "失败" in s:
                kind = "err"
            else:
                kind = "plain"
        self.log_text.insert("end", msg + "\n", kind)
        self.log_text.see("end")
        # 长跑时限制体积：超过 6000 行就砍掉前 2000 行
        if int(self.log_text.index("end-1c").split(".")[0]) > 6000:
            self.log_text.delete("1.0", "2000.0")

    def set_current(self, sid, name, status):
        label = {"running": "运行中", "ok": "已完成", "failed": "失败",
                 "timeout": "超时", "skipped": "跳过"}.get(status, status or "")
        self.lbl_current.config(
            text=f"当前步骤 {sid} · {name} · {label}",
            fg="#1565c0" if status == "running" else
               ("#c62828" if status in ("failed", "timeout") else "#33475b"))

    def set_node(self, sid, status, note=None):
        info = self.node_rows.get(sid)
        if info:
            self._paint(info, status, note)

    # ------------------------------------------------------------- 第 2 页

    def on_pick(self, sid):
        if self.editor.is_dirty():
            if not messagebox.askyesno(
                    "未保存", f"节点 {self.selected} 的修改尚未保存。\n"
                              f"放弃修改并切换到节点 {sid}？"):
                return

        self.selected = sid
        for s, info in self.pick_rows.items():
            self._paint(info, self._status_of(s), selected=(s == sid))

        _num, name, mod, why, _a = chain.BY_ID[sid]
        path = chain.step_file(mod)
        if not os.path.isfile(path):
            self.editor.load_text(f"# 文件不存在：{path}\n")
            self.lbl_file.config(text=f"缺失：{chain.rel(path)}", foreground="#c62828")
            self.btn_save.config(state="disabled")
            self.btn_revert.config(state="disabled")
            return

        self.editor.load(path)
        nlines = self.editor.line_count()
        self.lbl_file.config(
            text=f"节点 {sid} · {name} — {chain.rel(path)}  ({nlines} 行)",
            foreground="#555")
        self._refresh_save_buttons()

    def on_save(self):
        if not self.selected:
            return
        # 运行中禁止保存：正在跑的节点进程可能正读到半个文件
        if self.runner.is_running():
            messagebox.showwarning(
                "运行中", "编排正在运行，此刻保存会让节点读到不一致的代码。\n"
                          "请先停止，或等本次运行结束后再保存。")
            return
        ok, msg = self.editor.save()
        if ok:
            self.lbl_file.config(
                text=self.lbl_file.cget("text").split("  —")[0]
                     + f"  —  {msg}（下次运行生效）",
                foreground="#2e7d32")
            self.status(msg + "（下次运行生效）", "ok")
        else:
            messagebox.showerror("保存失败", msg)
        self._refresh_save_buttons()

    def on_revert(self):
        if not self.selected or not self.editor.path:
            return
        if not messagebox.askyesno("放弃修改", "重新从磁盘载入，丢弃当前修改？"):
            return
        self.editor.load(self.editor.path)
        self.status("已重新载入", "info")
        self._refresh_save_buttons()

    def _refresh_save_buttons(self):
        state = "normal" if self.editor.is_dirty() else "disabled"
        self.btn_save.config(state=state)
        self.btn_revert.config(state=state)

    def _status_of(self, sid):
        return self._last_status.get(sid)

    # ------------------------------------------------------------- 运行

    def on_run(self):
        if self.runner.is_running():
            return
        if self.editor.is_dirty() and self.selected:
            if not messagebox.askyesno(
                    "未保存", f"节点 {self.selected} 有未保存的修改。\n"
                              f"本次运行不会包含它们。仍要运行？"):
                return

        args = []
        if self.dry_run.get():
            args.append("--dry-run")
        only = self.only_var.get().strip()
        if only:
            args += ["--only", only]
        if self.resume_var.get():
            args.append("--resume")
        # 目标程序：只有显式选了才传 --target。
        # "" 必须**不传**（而不是传 "ww"）—— 否则「接着上次」续跑 ok-nte 时
        # 会被悄悄改回 ok-ww（main.py 的 --target 是覆盖语义）。
        tgt = TARGET_ARG.get(self.target_var.get().strip())
        if tgt:
            args += ["--target", tgt]

        self.log_text.delete("1.0", "end")
        self._last_status = {}
        for sid in self.node_rows:
            self._paint(self.node_rows[sid], None)
        self.set_current("—", "尚未开始", None)
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status("启动中…", "info")

        try:
            self.runner.start(self.python_var.get(), args)
        except OSError as e:
            messagebox.showerror("启动失败", f"{e}\n\n解释器：{self.python_var.get()}")
            self.btn_run.config(state="normal")
            self.btn_stop.config(state="disabled")
            return

        self.run_dir = None
        self.watcher.set_run_dir(None)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def _work(self):
        """worker 线程：读 stdout、认运行目录、轮询 state.json。"""
        try:
            for line in self.runner.proc.stdout:
                line = line.rstrip("\n")
                self.bus.log(line)
                if self.run_dir is None:
                    d = discover_run_dir_from_line(line)
                    if d:
                        self.run_dir = d
                        self.watcher.set_run_dir(d)
        except (ValueError, OSError):
            pass
        code = self.runner.proc.wait()
        self.bus.finished(code, self._exit_note(code))

    @staticmethod
    def _exit_note(code):
        return {0: "全部节点通过", 2: "环境前提不成立", 3: "校验失败/超时"}.get(
            code, f"退出码 {code}")

    def on_stop(self):
        if not self.runner.is_running():
            return
        if not messagebox.askyesno(
                "停止", "将强制终止**整个进程树**（主控 + 正在跑的节点）。\n\n"
                        "这是必要的：只杀主控会留下孤儿节点进程继续操作鼠标，\n"
                        "界面上显示「已停止」而鼠标还在自己动。\n\n确定停止？"):
            return
        note = self.runner.stop()
        self.status(note, "warn")
        self.append_log(f"[GUI] {note}", "warn")
        self.btn_run.config(state="normal")
        self.btn_stop.config(state="disabled")

    def on_finished(self, code, note):
        self.btn_run.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.status(f"结束：{note}", "ok" if code == 0 else "err")
        self.append_log(f"\n=== 编排结束：{note}（退出码 {code}）===",
                        "ok" if code == 0 else "err")
        # 结束后再读一次 state.json，把最终状态补齐
        raw = self.watcher.poll()
        if raw:
            self._apply_final(raw)

    def _apply_final(self, raw):
        for sid, rec in (raw.get("steps") or {}).items():
            st = rec.get("status")
            if st and st != "running":
                note = (rec.get("notes") or [None])[-1]
                self.set_node(sid, st, note)
        last = raw.get("last_step")
        if last and last in chain.BY_ID:
            self.set_node(last, raw.get("last_status") or "ok")

    # ------------------------------------------------------------- 事件泵

    def _pump(self):
        """主线程唯一的 widget 操作点。"""
        try:
            while True:
                kind, payload = self.bus.q.get_nowait()
                if kind == "log":
                    msg, tag = payload
                    self.append_log(msg, tag)
                elif kind == "node":
                    sid, name, status, note, elapsed = payload
                    # state.json 的状态名 -> 界面状态名
                    vis = {"ok": "ok", "failed": "failed", "timeout": "timeout",
                           "skipped": "skipped", "running": "running"}.get(
                        status, status)
                    self.set_node(sid, vis, note)
                    if status == "running":
                        shown = chain.BY_ID.get(sid, (None, name))[1]
                        self.set_current(sid, shown, "running")
                    elif sid == self.selected:
                        pass
                    self._last_status[sid] = vis
                elif kind == "finished":
                    self.on_finished(*payload)
                elif kind == "status":
                    self.status(*payload)
        except queue.Empty:
            pass

        # 轮询 state.json（运行中才需要）
        if self.runner.is_running() and self.watcher.run_dir:
            raw = self.watcher.poll()
            if raw:
                last = raw.get("last_step")
                if last and last in chain.BY_ID and raw.get("last_status"):
                    self._last_status[last] = raw["last_status"]

        if self.nb.index(self.nb.select()) == 1:
            self._refresh_save_buttons()
        self.after(120, self._pump)

    _last_status = {}

    # ------------------------------------------------------------- 状态栏

    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(fill="x", side="bottom")
        self.lbl_status = ttk.Label(bar, text="就绪", foreground="#555")
        self.lbl_status.pack(side="left")
        self.lbl_run = ttk.Label(bar, text="", foreground="#888")
        self.lbl_run.pack(side="right")

    def status(self, text, level="info"):
        color = {"info": "#555", "ok": "#2e7d32",
                 "warn": "#ef6c00", "err": "#c62828"}.get(level, "#555")
        self.lbl_status.config(text=text, foreground=color)
        if self.run_dir:
            self.lbl_run.config(text=chain.rel(self.run_dir))
        elif self.watcher.run_dir:
            self.lbl_run.config(text=chain.rel(self.watcher.run_dir) + "（上次）")

    # ------------------------------------------------------------- 启动校验

    def _check_chain(self):
        """清单与磁盘比对。**警告，不崩溃** —— GUI 必须在链条坏掉时还能开。"""
        problems = chain.verify_against_disk()
        if not problems:
            self.status("就绪 — 步骤清单与 steps/ 一致", "ok")
            return
        self.status(f"⚠ 步骤清单有 {len(problems)} 处问题（见日志）", "warn")
        for p in problems:
            self.append_log(f"[警告] {p}", "warn")
        self.append_log("", "plain")
        self.append_log("[提示] 以上问题不影响 GUI 打开与改代码；"
                        "但运行编排前应先修好。", "warn")

    def on_close(self):
        if self.runner.is_running():
            if not messagebox.askyesno(
                    "仍在运行", "编排仍在运行。关闭窗口会终止整个进程树。\n"
                                "确定关闭？"):
                return
            self.runner.stop()
        if self.editor.is_dirty():
            if not messagebox.askyesno(
                    "未保存", f"节点 {self.selected} 有未保存的修改。\n"
                              f"确定放弃并关闭？"):
                return
        self.destroy()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m gui", description="ok-ww 断点式编排 — 两页 GUI")
    ap.add_argument("--dry-run", action="store_true", help="启动时勾选 dry-run")
    ap.add_argument("--only", default=None, help="启动时预选「只跑节点 N」")
    args = ap.parse_args(argv)

    app = App(dry_run=args.dry_run, only=args.only)
    app.mainloop()
    return 0
