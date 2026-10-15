"""orchestrator.gui — 最小可运行 GUI 骨架

**这是骨架，不是成品。** 目的是让你看到实物、验证观感与线程模型，
而不是一次交付完整功能。

设计约束（全部来自实测，见 docs/GUI-DEPENDENCY-DECISION.md）：

  1. **同进程**：GUI 与编排核心必须在**同一个进程**里，因为
     `win32.ensure_dpi_aware()` 必须在「拥有窗口的进程」且「窗口创建之前」调用。
     故本文件**直接 import orchestrator**，不 Popen 子进程。
  2. **tkinter 不是线程安全的**：编排跑在 worker 线程，但**任何 UI 操作
     都只能由主线程执行**。两者之间用 `queue.Queue` 传递事件，主线程用
     `after()` 轮询队列。**worker 绝不碰 widget。**
  3. **零新增依赖**：只用标准库。

运行：

    python -m orchestrator.gui
    python -m orchestrator.gui --dry-run

⚠️ 提权：本 GUI 自身不做 UAC 自提权。未提权时顶部显示常驻警告横幅，
   且清理阶段不会执行（对应你裁决里的 Q10 降级路径 b）。
"""

import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from tkinter import messagebox

from . import win32

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


# ======================================================================
# 事件通道：worker 线程 -> 主线程
# ======================================================================

class EventBus:
    """worker 线程与主线程之间**唯一**的通信渠道。

    worker 只往队列里放数据（绝不碰 widget），主线程按帧取。
    """

    def __init__(self):
        self.q = queue.Queue()

    def log(self, msg):
        self.q.put(("log", msg))

    def node(self, index, name, status):
        """节点状态变化。status: running | done | failed | skipped"""
        self.q.put(("node", (index, name, status)))

    def finished(self, exit_code, summary):
        self.q.put(("finished", (exit_code, summary)))

    def frame_shot(self, path):
        """有新的落盘帧可预览。"""
        self.q.put(("shot", path))


class ProgressLog:
    """喂给 Orchestrator 的 log 回调，同时解析出「当前节点」。

    Orchestrator 的日志形如 `\\n[节点 5] 等待窗口就绪（...）`，
    这里把它转成结构化事件，供 GUI 高亮节点列表。
    """

    NODE_RE = None  # 延迟编译

    def __init__(self, bus):
        self.bus = bus
        self.current = None

    def __call__(self, msg=""):
        import re
        if ProgressLog.NODE_RE is None:
            ProgressLog.NODE_RE = re.compile(r"^\[节点\s*(\d+)\]\s*(.*)$")

        m = ProgressLog.NODE_RE.match(msg.strip())
        if m:
            idx = int(m.group(1))
            name = m.group(2).strip()
            if self.current is not None and self.current != idx:
                self.bus.node(self.current, "", "done")
            self.current = idx
            self.bus.node(idx, name, "running")
        self.bus.log(msg)

    def close(self):
        pass


# ======================================================================
# 编排 worker
# ======================================================================

def run_orchestrator(bus, dry_run):
    """在 worker 线程里跑一遍编排。只通过 bus 回报。"""
    exit_code = 1
    summary = "未开始"
    try:
        from .orchestrator import Orchestrator

        log = ProgressLog(bus)
        orch = Orchestrator(
            dry_run=dry_run,
            log_dir=os.path.join(REPO, "logs"),
            out_dir=os.path.join(REPO, "logs", "shots"),
        )
        # Orchestrator 在 __init__ 里自建 Log；这里替换成我们的回调
        orch.log = log

        log(f"GUI 启动编排  dry_run={dry_run}  提权={win32.is_admin()}")

        # 把落盘帧也送进预览：包一层 shot
        orig_shot = orch.shot

        def shot(frame, tag):
            path = orig_shot(frame, tag)
            bus.frame_shot(path)
            return path

        orch.shot = shot

        exit_code = orch.run()
        summary = {0: "成功", 2: "环境前提不成立", 3: "不变量被破坏",
                   4: "超时", 5: "未预期异常"}.get(exit_code, f"退出码 {exit_code}")
    except Exception as e:
        import traceback
        bus.log(f"[GUI] worker 异常：{type(e).__name__}: {e}")
        bus.log(traceback.format_exc())
        summary = f"{type(e).__name__}: {e}"
        exit_code = 5
    finally:
        bus.finished(exit_code, summary)


# ======================================================================
# 节点清单（来自 orchestrator/orchestrator.py 的节点划分）
# ======================================================================

NODES = [
    (1, "提权检查", "非管理员直接中止（INV-7）"),
    (2, "启动 ok-ww.exe", "第一层会自动放行"),
    (4, "等待第二层", "窗口持有者 pythonw.exe"),
    (5, "等待窗口就绪", "标题正则 + rect 稳定"),
    (6, "抓首帧校验", "INV-1 尺寸 / INV-13 非全黑 / 身份"),
    (7, "置前台 + 遮挡判定", "INV-8 / INV-22 / INV-23"),
    (8, "任务循环", "导航 → 定位 → 点击 → 等完成"),
    (9, "退出与清理", "正常完成不杀；超时/失败才杀"),
]


# ======================================================================
# 主窗口
# ======================================================================

class App(tk.Tk):
    def __init__(self, dry_run=False):
        super().__init__()
        self.title("ok-ww 黑盒编排 — GUI 骨架")
        self.geometry("1180x720")
        self.minsize(900, 560)

        self.bus = EventBus()
        self.worker = None
        self.dry_run = tk.BooleanVar(value=dry_run)
        self.node_rows = {}

        self._build_style()
        self._build_widgets()
        self._poll()

    # --- 外观 ---------------------------------------------------------

    def _build_style(self):
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        self.configure(bg="#f5f5f5")

    def _build_widgets(self):
        # 顶部：提权警告横幅（常驻，若未提权）
        self.banner = tk.Frame(self, bg="#c62828")
        self.banner_label = tk.Label(
            self.banner, bg="#c62828", fg="white", anchor="w",
            font=("Microsoft YaHei UI", 10, "bold"), padx=10, pady=6)
        self.banner_label.pack(fill="x")
        if not win32.is_admin():
            self.banner_label.config(
                text="⚠ 未提权运行 —— 清理阶段无法终止 ok-ww 进程。"
                     "请以管理员身份重启本程序（Q10 降级路径 b）")
            self.banner.pack(fill="x", side="top")

        # 工具栏
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x", side="top")

        self.btn_run = ttk.Button(bar, text="▶ 运行编排", command=self.on_run)
        self.btn_run.pack(side="left")

        self.btn_stop = ttk.Button(bar, text="■ 停止", command=self.on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=(6, 0))

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", padx=10)
        ttk.Checkbutton(bar, text="dry-run（不点击、不杀进程）",
                        variable=self.dry_run).pack(side="left")

        self.lbl_state = ttk.Label(bar, text="就绪", foreground="#555")
        self.lbl_state.pack(side="right")

        # 主体：左节点列表 / 右日志+预览
        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # --- 左：节点清单 ---
        left = ttk.Labelframe(main, text="编排节点", padding=6)
        main.add(left, weight=1)

        for idx, name, note in NODES:
            row = tk.Frame(left, bg="#ffffff", bd=0, highlightthickness=0)
            row.pack(fill="x", pady=1)

            dot = tk.Label(row, text="○", width=2, bg="#ffffff",
                           fg="#999", font=("Segoe UI", 11))
            dot.pack(side="left")

            txt = tk.Frame(row, bg="#ffffff")
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=f"[{idx}] {name}", bg="#ffffff", anchor="w",
                     font=("Microsoft YaHei UI", 9, "bold")).pack(fill="x")
            tk.Label(txt, text=note, bg="#ffffff", anchor="w", fg="#888",
                     font=("Microsoft YaHei UI", 8)).pack(fill="x")

            self.node_rows[idx] = {"frame": row, "dot": dot, "txt": txt,
                                   "title": txt.winfo_children()[0],
                                   "note": txt.winfo_children()[1]}

        # --- 右：日志 + 帧预览 ---
        right = ttk.PanedWindow(main, orient="vertical")
        main.add(right, weight=3)

        logf = ttk.Labelframe(right, text="运行日志", padding=4)
        right.add(logf, weight=3)

        self.log_text = tk.Text(logf, wrap="none", height=18,
                                font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="#d4d4d4")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logf, orient="vertical",
                           command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)

        self.log_text.tag_configure("ok", foreground="#4ec9b0")
        self.log_text.tag_configure("warn", foreground="#dcdcaa")
        self.log_text.tag_configure("err", foreground="#f48771")
        self.log_text.tag_configure("node", foreground="#569cd6")

        prevf = ttk.Labelframe(right, text="帧预览（抓图落盘复核）", padding=4)
        right.add(prevf, weight=2)

        self.preview = tk.Label(prevf, text="（尚无帧）", bg="#fafafa",
                                fg="#999", font=("Microsoft YaHei UI", 9))
        self.preview.pack(fill="both", expand=True)
        self._preview_img = None

    # --- 日志 ---------------------------------------------------------

    def append_log(self, msg):
        tag = ""
        s = msg.strip()
        if s.startswith("[节点"):
            tag = "node"
        elif "[OK]" in s:
            tag = "ok"
        elif "[警告]" in s or "[!!]" in s or "未提权" in s:
            tag = "warn"
        elif "[中止]" in s or "[异常]" in s or "失败" in s:
            tag = "err"

        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        # 防止长跑时无限增长（保留最后 4000 行）
        if int(self.log_text.index("end-1c").split(".")[0]) > 4000:
            self.log_text.delete("1.0", "800.0")

    # --- 节点状态 -----------------------------------------------------

    COLORS = {
        "running": ("▶", "#1565c0", "#e3f2fd"),
        "done":    ("✔", "#2e7d32", "#ffffff"),
        "failed":  ("✖", "#c62828", "#ffffff"),
        "skipped": ("–", "#999999", "#ffffff"),
    }

    def set_node(self, idx, status):
        row = self.node_rows.get(idx)
        if not row:
            return
        dot_text, color, bg = self.COLORS.get(status, ("○", "#999", "#ffffff"))
        row["dot"].config(text=dot_text, fg=color)
        for w in (row["frame"], row["dot"], row["txt"],
                  row["title"], row["note"]):
            w.config(bg=bg)
        # running 时加粗标题
        row["title"].config(
            font=("Microsoft YaHei UI", 9, "bold" if status == "running" else "normal"))

    def reset_nodes(self):
        for idx in self.node_rows:
            self.set_node(idx, "skipped")

    # --- 帧预览 -------------------------------------------------------

    def show_frame(self, path):
        """把落盘帧显示出来。

        用 PIL.ImageTk —— Pillow 已在项目依赖里，未引入新依赖。
        缩放到预览区大小，保持纵横比。
        """
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self.append_log("[GUI] 无 Pillow，跳过帧预览")
            return
        try:
            img = Image.open(path)
            avail_w = max(self.preview.winfo_width(), 200)
            avail_h = max(self.preview.winfo_height(), 100)
            img.thumbnail((avail_w, avail_h), Image.LANCZOS)
            self._preview_img = ImageTk.PhotoImage(img)
            self.preview.config(image=self._preview_img, text="")
        except Exception as e:
            self.append_log(f"[GUI] 预览失败 {path}: {e}")

    # --- 事件循环 -----------------------------------------------------

    def _poll(self):
        """主线程轮询队列 —— **只有这里可以碰 widget**。"""
        try:
            while True:
                kind, payload = self.bus.q.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "node":
                    idx, name, status = payload
                    self.set_node(idx, status)
                    if name:
                        self.lbl_state.config(text=f"运行中：[{idx}] {name}")
                elif kind == "shot":
                    self.show_frame(payload)
                elif kind == "finished":
                    self.on_finished(*payload)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    # --- 运行控制 -----------------------------------------------------

    def on_run(self):
        if self.worker and self.worker.is_alive():
            return
        self.log_text.delete("1.0", "end")
        self.reset_nodes()
        self.preview.config(image="", text="（尚无帧）")
        self._preview_img = None
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_state.config(text="启动中…", foreground="#1565c0")

        self.worker = threading.Thread(
            target=run_orchestrator,
            args=(self.bus, self.dry_run.get()),
            daemon=True,          # 关窗即随主进程退出
        )
        self.worker.start()

    def on_stop(self):
        """停止：编排是同步循环，无法安全中断，故只做说明。

        真要中断只能杀进程 —— 那也是清理路径的一部分。
        """
        messagebox.showinfo(
            "停止",
            "编排是同步循环，无法从外部安全中断。\n\n"
            "当前实现不强行终止线程（会让进程处于半清理状态）。\n"
            "要中止请直接关闭窗口，或等待当前节点超时。\n\n"
            "（这是骨架的已知限制，正式实现需要给 Orchestrator 加\n"
            " 一个可轮询的 cancel 事件。）")

    def on_finished(self, exit_code, summary):
        self.btn_run.config(state="normal")
        self.btn_stop.config(state="disabled")
        ok = exit_code == 0
        self.lbl_state.config(
            text=f"结束：{summary}",
            foreground="#2e7d32" if ok else "#c62828")
        self.append_log(f"\n=== 编排结束：{summary}（退出码 {exit_code}）===")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m orchestrator.gui",
                                 description="ok-ww 黑盒编排 GUI（骨架）")
    ap.add_argument("--dry-run", action="store_true",
                    help="不点击、不杀进程，只走校验逻辑")
    args = ap.parse_args(argv)

    # 关键：DPI 感知必须在**创建任何窗口之前**声明，且与编排同进程。
    # 这正是 tkinter 方案相对浏览器方案的架构优势（见选型文档 §3）。
    win32.ensure_dpi_aware()

    app = App(dry_run=args.dry_run)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
