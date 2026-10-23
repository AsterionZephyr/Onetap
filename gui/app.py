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
from . import targets as gui_targets
from .editor import CodeEditor
from .runner import Runner, StateWatcher, discover_run_dir_from_line

# 配色：与旧骨架一致（已肉眼复核过观感，见 docs/GUI.md §7.3）
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

# 步骤行副标题（note）的**显示**上限。
#
# 为什么要有：note 是节点写进 state.json 的**全量证据**。节点 8 完成后是
#     completed：汇总 success=[...7 项...] failed=[] skipped=['异象追猎']；
#     终止标记=True 日常结束=True 杀游戏=False；出现终止标记（进程收尾）
# （ok-nte 实测 110 字符）。而 Tk 的 Label 在**没有 wraplength** 时
# 「请求宽度 = 文本宽度」，这个宽度会被 pack/grid 算进左栏的自然宽度 ⇒
# 左栏（本应 1/5）被撑到 ~380px、右侧日志被挤窄（2026-10-20 用户截图发现）。
#
# 步骤行只是**摘要**：完整 note 在 state.json，完整 detail 在日志面板里。
# 两件事一起做，缺一不可：
#   ① 截断到 NOTE_MAX 个字符 + "…" —— 长度可预期，行高不随证据膨胀；
#   ② 标签设 wraplength = NOTE_WRAP 兜底 —— 以后再长的 note 只会折行，
#      绝不把列宽撑开（截断管"短"，兜底管"宽度下限"）。
NOTE_MAX = 26
NOTE_WRAP = 200


def _short_note(note, limit=NOTE_MAX):
    """note -> **单行**摘要：折叠所有空白；超过 limit 个字符就截断加 "…"。

    ⚠️ 只影响**界面显示**。state.json 的 `notes` 与主控日志里的 detail
    一律保持原文 —— VERDICT.md 的证据链不能因为界面变短而丢东西。
    """
    s = " ".join(str(note).split())
    if len(s) <= limit:
        return s
    return s[:max(1, limit - 1)].rstrip() + "\u2026"


# 目标程序清单：**任意多选**，来源见 gui/targets.py（ast 静态读
# orchestrator/programs.py，读不出来就回落兜底值并在界面上告警）。
# ⚠️ 与 gui/chain.py 同样的理由：这里**独立声明**，不 import orchestrator，
# 否则 main.py 一坏，GUI 连修它的界面都打不开。
TARGET_PROGRAMS, TARGET_PROBLEMS = gui_targets.load()

# 选择器从「单选下拉」改成「多选列表」后，不再有 "两个都跑" 这种枚举项 ——
# 勾几个就传几个（`--target ww,nte`），顺序 = 这里的声明顺序。
# 「跟随上次记录」（不传 --target）仍保留为一个独立开关：
# 少了它，`接着上次` 续跑 ok-nte 会被悄悄改回默认程序。


class Bus:
    """worker -> 主线程的唯一通道。只放数据，不放 widget 操作。"""

    def __init__(self):
        self.q = queue.Queue()

    def log(self, msg, kind=None):
        self.q.put(("log", (msg, kind)))

    def node(self, target, sid, name, status, note=None, elapsed=None):
        """一条节点状态。`target` = 程序 key（未知时传 None）。"""
        self.q.put(("node", (target, sid, name, status, note, elapsed)))

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
        # 目标程序：多选。默认「跟随上次记录」= 不传 --target
        # （读 state.json 里记录的程序；`接着上次` 续跑 ok-nte 时不会被改回 ww）。
        self.follow_var = tk.BooleanVar(value=True)
        self.target_vars = {k: tk.BooleanVar(value=True) for k, _d in TARGET_PROGRAMS}
        # 执行顺序（可在界面上任意调整）：默认 = 清单声明顺序。
        # selected_targets() 按它过滤勾选项 —— 这个顺序就是传给 --target 的顺序，
        # 也就是 run_multi 实际串行执行的顺序。
        self._order = [k for k, _d in TARGET_PROGRAMS]
        # 步骤区显示哪个目标的节点状态；None = 跟着正在跑的那个走
        self._view_target = None
        # 最近一次收到节点状态的目标（None = 还没收到 / 不知道）
        self._active_target = None
        # target -> {sid: (status, note)}；target 为 None 表示"还不知道"
        self._tstate = {}
        self.python_var = tk.StringVar(value=sys.executable)

        self.node_rows = {}      # 第 1 页的步骤行（属于 self._scope_key 这个程序）
        self.pick_rows = {}      # 第 2 页的步骤行（同上）
        self.selected = None     # 第 2 页当前打开的节点编号
        self._scope_key = None   # 两页当前按哪个目标程序的清单建行
        self._picked_scope = None  # self.selected 是从哪个程序载入的

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

        # 左：目标（多选）+ 步骤列表
        left = ttk.Labelframe(page, text="目标与步骤", padding=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)

        self._build_target_selector(left)

        # 步骤行的表头：说明下面这 8 行显示的是**哪个目标**的进度
        self.lbl_scope = tk.Label(
            left, text="步骤状态：—", bg=BG, fg="#33475b", anchor="w",
            font=("Microsoft YaHei UI", 9, "bold"))
        self.lbl_scope.pack(fill="x", pady=(6, 2))

        self.run_list = tk.Frame(left, bg="#ffffff")
        self.run_list.pack(fill="both", expand=True)
        # 第 1 页的行属于**当前显示的那个程序**（见 _scope_target()）。
        self._scope_key = self._scope_target()
        self._rebuild_rows(self.run_list, self.node_rows)

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
        # 目标程序选择器不在这里：它在左栏（多选列表，见 _build_target_selector）。
        # 控制条只留一个只读的摘要，省得运行时忘了自己勾了什么。
        self.lbl_targets = ttk.Label(ctl, text="", foreground="#555")
        self.lbl_targets.pack(side="left")
        ttk.Label(ctl, text="只跑节点").pack(side="left", padx=(12, 2))
        # 候选 = **当前显示的那个程序**自己的节点编号（切目标时刷新，见
        # _refresh_only_values()）：同一编号在不同程序里可能不存在。
        self.cmb_only = ttk.Combobox(ctl, textvariable=self.only_var, width=4,
                                     state="readonly", values=[])
        self.cmb_only.pack(side="left")
        self._refresh_only_values()
        ttk.Checkbutton(ctl, text="接着上次", variable=self.resume_var).pack(
            side="left", padx=(12, 0))
        # lbl_targets 是在本函数里才建的，选择器构建时它还不存在 ——
        # 这里补一次刷新，否则启动后控制条上的目标摘要一直是空白的。
        self._on_targets_changed()
        self._repaint_steps()

    # --- 目标程序选择器（任意多选 + 任意执行顺序）---------------------

    def _build_target_selector(self, parent):
        """左栏顶部的目标选择器。

        四件独立的东西，别混：

            ☐ 跟随上次记录        完全不传 --target（读 state.json 的记录）
            ☑ ok-ww / ☑ ok-nte    传 `--target ww,nte`（跑不跑由勾选决定）
            行首的 1 2 3 + ↑↓      **执行顺序**（任意调整；顺序 = --target 的顺序）
            行尾的 ✔ 8/8          该程序**正在跑的那一轮**的进度（与勾选无关）

        为什么不是 Combobox：Combobox 只能单选，而需求是「任意多选 + 全选」。
        Tk 没有现成的多选列表控件，最低成本且状态一眼可见的做法就是
        Checkbutton 一列 + 全选/清空两个按钮；顺序用每行一对 ↑/↓ 改
        （拖拽要自己实现命中测试与占位线，且与本页「点行=查看该程序清单」
        的手势冲突，收益不值）。

        ⚠️ 行**必须**挂在独立的 rows_box 里：调整顺序靠重排 pack，若行与下面的
        按钮/说明同挂 box，重新 pack 会把行挪到它们**下面**（pack 顺序 = 调用顺序）。
        """
        box = ttk.Frame(parent)
        box.pack(fill="x")

        self.chk_follow = ttk.Checkbutton(
            box, text="跟随上次记录（不传 --target）",
            variable=self.follow_var, command=self._on_targets_changed)
        self.chk_follow.pack(anchor="w")

        self._rows_box = tk.Frame(box, bg=BG)
        self._rows_box.pack(fill="x")

        self._target_rows = {}
        for key, disp in TARGET_PROGRAMS:
            row = tk.Frame(self._rows_box, bg=BG)
            idx = tk.Label(row, text="1", width=2, bg=BG, fg="#9e9e9e",
                           anchor="e", font=("Segoe UI", 9))
            idx.pack(side="left")
            chk = ttk.Checkbutton(row, text=disp, variable=self.target_vars[key],
                                  command=lambda k=key: self._on_target_chk(k))
            chk.pack(side="left")
            dot = tk.Label(row, text="\u25cb", bg=BG, fg="#9e9e9e",
                           font=("Segoe UI", 9))
            dot.pack(side="right")
            # side="right" 的 pack 是**从右往左**排的：先 pack 的在最右边。
            btn_down = ttk.Button(row, text="\u2193", width=2,
                                  command=lambda k=key: self._move_target(k, 1))
            btn_down.pack(side="right")
            btn_up = ttk.Button(row, text="\u2191", width=2,
                                command=lambda k=key: self._move_target(k, -1))
            btn_up.pack(side="right")
            self._target_rows[key] = {"row": row, "idx": idx, "chk": chk,
                                      "dot": dot, "disp": disp,
                                      "up": btn_up, "down": btn_down}
            for w in (row, idx, dot):
                w.bind("<Button-1>",
                       lambda e, k=key: self.on_view_target(k))
                w.configure(cursor="hand2")

        btns = tk.Frame(box, bg=BG)
        btns.pack(fill="x", pady=(2, 0))
        self.btn_all = ttk.Button(btns, text="全选", width=6,
                                  command=self.on_select_all)
        self.btn_all.pack(side="left")
        self.btn_none = ttk.Button(btns, text="清空", width=6,
                                   command=self.on_select_none)
        self.btn_none.pack(side="left", padx=(4, 0))
        self.btn_default_order = ttk.Button(btns, text="\u21ba 默认序", width=9,
                                            command=self.on_default_order)
        self.btn_default_order.pack(side="left", padx=(4, 0))

        self.lbl_pick = tk.Label(box, text="", bg=BG, fg="#555", anchor="w",
                                 wraplength=210, justify="left",
                                 font=("Microsoft YaHei UI", 8))
        self.lbl_pick.pack(fill="x", pady=(2, 0))
        self._reflow_target_rows()
        self._on_targets_changed()

    def _on_targets_changed(self):
        """跟随开关一变，就刷新清单下方的说明与运行摘要。

        这里**不置灰**多选列表 —— 两个原因：
        1. ttk 在 vista 主题下把「disabled + 已勾」画成一个空白灰方框，
           看起来跟「没勾」一模一样（实测截图如此），比不置灰更误导；
        2. 跟随中直接勾一个程序，本来就是用户想切到手动的自然动作
           （见 _on_target_chk，勾一下自动关掉跟随）。
        运行期间的选择器锁定在 _set_target_controls 里做，是另一回事。
        """
        follow = bool(self.follow_var.get())
        if follow:
            text = "运行哪个程序：跟随 state.json 里记录的那个\n（勾选暂不生效，勾一下即改为手动）"
        else:
            picked = self.selected_targets()
            if not picked:
                text = "⚠ 未勾选任何程序 —— 点「全选」或勾一个"
            else:
                disp = dict(TARGET_PROGRAMS)
                text = "将依次运行：" + " → ".join(disp.get(k, k) for k in picked)
        if hasattr(self, "lbl_pick"):
            self.lbl_pick.config(text=text)
        if hasattr(self, "lbl_targets"):
            self.lbl_targets.config(text=self._targets_summary())
        # 显示哪个程序的清单由勾选/跟随决定 —— 变了就重建节点行。
        self._sync_scope()

    def _targets_summary(self):
        if self.follow_var.get():
            return "目标：跟随记录"
        picked = self.selected_targets()
        return "目标：" + (",".join(picked) if picked else "（未选）")

    def selected_targets(self):
        """勾选的程序 key，顺序 = self._order（= 界面上 1 2 3 的顺序）。

        ⚠️ 这里**不能**遍历 TARGET_PROGRAMS：那会把顺序钉死成声明顺序，
        界面上的 ↑/↓ 就成了纯装饰 —— 看着换了顺序、实际执行顺序没变，
        正是本仓库反复踩的静默失效。
        """
        if self.follow_var.get():
            return []
        return [k for k in self._order if self.target_vars[k].get()]

    # --- 执行顺序（任意调整）------------------------------------------

    def _reflow_target_rows(self):
        """按 self._order 重排行，并刷新序号与 ↑/↓ 的可用性（首尾禁用）。"""
        for key in self._order:
            self._target_rows[key]["row"].pack_forget()
        last = len(self._order) - 1
        for i, key in enumerate(self._order):
            r = self._target_rows[key]
            r["row"].pack(fill="x")
            r["idx"].config(text=str(i + 1))
            r["up"].config(state="normal" if i > 0 else "disabled")
            r["down"].config(state="normal" if i < last else "disabled")

    def _move_target(self, key, delta):
        """把某个程序上移/下移一格（delta = -1 / +1）。

        顺序只在手动模式下有意义（跟随记录时根本不传 --target），故与勾选
        同一处理：动一下 = 明确要手动，自动关掉跟随，避免"改了顺序却没生效"。
        """
        if key not in self._order:
            return
        i = self._order.index(key)
        j = i + delta
        if not (0 <= j < len(self._order)):
            return
        if self.follow_var.get():
            self.follow_var.set(False)
        self._order[i], self._order[j] = self._order[j], self._order[i]
        self._reflow_target_rows()
        self._on_targets_changed()

    def on_default_order(self):
        """恢复默认顺序（= programs.ALL 的声明顺序）。

        与勾选/加减序同一处理：点它 = 明确在调执行顺序，只在手动模式下有意义，
        所以也把「跟随上次记录」关掉 —— 否则跟随中点了它，界面看着复位了、
        实际仍按记录跑（静默失效）。
        """
        if self.follow_var.get():
            self.follow_var.set(False)
        self._order = [k for k, _d in TARGET_PROGRAMS]
        self._reflow_target_rows()
        self._on_targets_changed()

    def on_select_all(self):
        self.follow_var.set(False)
        for v in self.target_vars.values():
            v.set(True)
        self._on_targets_changed()

    def on_select_none(self):
        self.follow_var.set(False)
        for v in self.target_vars.values():
            v.set(False)
        self._on_targets_changed()

    def _on_target_chk(self, key):
        """直接勾/取消某个程序：跟随中勾选 = 想手动选，自动关掉跟随。

        不自动关的话，用户会看到「勾了 ok-ww」但实际仍按记录跑，
        还以为是勾选不灵 —— 静默失效，正是本仓库反复踩的坑。
        """
        if self.follow_var.get():
            self.follow_var.set(False)
        self._on_targets_changed()

    def _set_target_controls(self, enabled):
        """运行期间锁住选择器：改了也不会生效，只会让人以为生效了。"""
        if not hasattr(self, "_target_rows"):
            return
        if enabled:
            # 先按当前的 _order 重排：_reflow 会把首尾的 ↑/↓ 重新禁用，
            # 比在这里逐个恢复更不容易漏（漏了就是"运行期点得动"的假象）。
            self._reflow_target_rows()
            self._on_targets_changed()
            self.chk_follow.config(state="normal")
            self.btn_default_order.config(state="normal")
        else:
            for r in self._target_rows.values():
                r["chk"].config(state="disabled")
                r["up"].config(state="disabled")
                r["down"].config(state="disabled")
            for btn in (self.btn_all, self.btn_none, self.btn_default_order):
                btn.config(state="disabled")
            self.chk_follow.config(state="disabled")

    def on_view_target(self, key):
        """点某个目标 -> 两页的节点行切到它。None = 自动跟随当前在跑的那个。"""
        self._view_target = None if self._view_target == key else key
        self._sync_scope()
        self._repaint_steps()

    # --- 第 2 页 ------------------------------------------------------

    def _build_page_code(self, page):
        page.columnconfigure(0, weight=1, minsize=200)   # 1/5，与第 1 页一致
        page.columnconfigure(1, weight=4)
        page.rowconfigure(0, weight=1)

        left = ttk.Labelframe(page, text="步骤", padding=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)
        self.pick_list = tk.Frame(left, bg="#ffffff")
        self.pick_list.pack(fill="both", expand=True)
        self._rebuild_rows(self.pick_list, self.pick_rows,
                           on_click=self.on_pick)

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

    def _make_row(self, parent, sid, name, has_args=False, on_click=None):
        """一行：序号（等宽，像代码行号）+ 名称（★ = 有专属参数）+ 状态点。"""
        row = tk.Frame(parent, bg="#ffffff", bd=0, highlightthickness=0)
        row.pack(fill="x", pady=1)

        num = tk.Label(row, text=f"{sid:>2}", width=3, bg="#f0f0f0",
                       fg="#7a7a7a", font=("Consolas", 10, "bold"))
        num.pack(side="left", fill="y")

        body = tk.Frame(row, bg="#ffffff")
        body.pack(side="left", fill="x", expand=True, padx=(6, 2))
        # ★ = 该节点有程序专属参数（清单里的 has_args；细节看该模组的 -h）
        title = tk.Label(body, text=(name + " ★") if has_args else name,
                         bg="#ffffff", anchor="w",
                         font=("Microsoft YaHei UI", 9, "bold"))
        title.pack(fill="x")
        # wraplength 是**防撑宽**的最后一道闸：没有它时 Label 的"请求宽度"
        # 等于整行文本宽度，grid 会把左栏按这条最长 note 撑开（见 NOTE_MAX 注释）。
        sub = tk.Label(body, text="", bg="#ffffff", anchor="w", fg="#8a8a8a",
                       font=("Microsoft YaHei UI", 8), justify="left",
                       wraplength=NOTE_WRAP)
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

    # --- 按目标程序重建节点行 ------------------------------------------
    #
    # 节点链**属于程序**：同一编号在不同程序里可能不存在、文案也可能不同。
    # 所以切换目标时整列重建，绝不复用旧行。

    def _scope_target(self):
        """两页当前显示/校验哪个程序的清单。"""
        known = dict(TARGET_PROGRAMS)
        t = self._effective_view_target()
        if t in known:
            return t
        picked = self.selected_targets()
        if picked:
            return picked[0]
        return TARGET_PROGRAMS[0][0] if TARGET_PROGRAMS else None

    def _ids_of(self, key):
        """某程序的节点编号顺序；key 为空时返回所有程序编号的并集。"""
        keys = [key] if key else [k for k, _d in TARGET_PROGRAMS]
        out = []
        for k in keys:
            for sid in chain.ids(k):
                if sid not in out:
                    out.append(sid)
        return out

    def _all_sids(self):
        return set(self._ids_of(None))

    def _node_row(self, key, sid):
        """(sid, label, name, why, has_args) 或 None。"""
        if not key:
            return None
        for row in chain.nodes(key):
            if row[0] == sid:
                return row
        return None

    def _rebuild_rows(self, parent, store, on_click=None):
        """按 self._scope_key 的清单重建一列行（先销毁旧行）。"""
        for child in parent.winfo_children():
            child.destroy()
        store.clear()
        if not self._scope_key:
            return
        for sid, label, _name, _why, has_args in chain.nodes(self._scope_key):
            store[sid] = self._make_row(parent, sid, label,
                                        has_args=has_args, on_click=on_click)

    def _refresh_only_values(self):
        """「只跑节点」下拉的候选 = 当前程序自己的编号。"""
        ids = self._ids_of(self._scope_key)
        if hasattr(self, "cmb_only"):
            self.cmb_only.config(values=[""] + ids)
        cur = self.only_var.get().strip()
        if cur and cur not in ids:
            self.only_var.set("")

    def _sync_scope(self):
        """目标程序变了就重建两页的节点行，并让编辑器跟着换文件。

        编辑器**绝不因切换目标丢掉未保存的修改**：脏的内容原样保留，只把
        选择标记摘掉（_picked_scope 与当前程序不符），文件名栏说明它原属谁。
        """
        key = self._scope_target()
        if not hasattr(self, "run_list"):       # 控件还没建好
            self._scope_key = key
            return
        if key == self._scope_key:
            self._refresh_only_values()
            return
        old = self._scope_key
        self._scope_key = key
        self._rebuild_rows(self.run_list, self.node_rows)
        if hasattr(self, "pick_list"):
            self._rebuild_rows(self.pick_list, self.pick_rows,
                               on_click=self.on_pick)
        self._refresh_only_values()
        if hasattr(self, "editor") and self.selected is not None:
            if self.editor.is_dirty():
                self.lbl_file.config(
                    text=f"⚠ 未保存的修改仍在编辑器里（原属 "
                         f"{self._target_label(old)} 节点 {self.selected}）；"
                         f"已切到 {self._target_label(key)}，点节点行会重新载入",
                    foreground="#ef6c00")
            else:
                # 未保存时绝不换文件；不脏就按新程序重新载入（节点不存在时
                # _load_node 会在文件名栏说明，并禁用保存按钮）。
                self._load_node(self.selected)
        self._repaint_picks()
        self._repaint_steps()

    def _repaint_picks(self):
        for sid, info in self.pick_rows.items():
            selected = (sid == self.selected
                        and self._picked_scope == self._scope_key)
            self._paint(info, self._status_of(sid), selected=selected)

    def _load_node(self, sid):
        """把该节点在**当前程序**下的文件载入编辑器（不弹任何对话框）。"""
        key = self._scope_key
        self.selected = sid
        self._picked_scope = key
        row = self._node_row(key, sid)
        if row is None:
            self.editor.load_text(
                f"# {self._target_label(key)} 的链条里没有节点 {sid}\n")
            self.lbl_file.config(
                text=f"节点 {sid} 不在 {self._target_label(key)} 的链条里",
                foreground="#c62828")
            self.btn_save.config(state="disabled")
            self.btn_revert.config(state="disabled")
            return False
        _sid, label, name, _why, _a = row
        path = chain.step_file(key, row)
        if not os.path.isfile(path):
            self.editor.load_text(f"# 文件不存在：{path}\n")
            self.lbl_file.config(text=f"缺失：{chain.rel(path)}",
                                 foreground="#c62828")
            self.btn_save.config(state="disabled")
            self.btn_revert.config(state="disabled")
            return False
        self.editor.load(path)
        nlines = self.editor.line_count()
        self.lbl_file.config(
            text=f"节点 {sid} · {label}（{name}）  — {chain.rel(path)}"
                 f"  ({nlines} 行)",
            foreground="#555")
        self._refresh_save_buttons()
        return True

    def _paint(self, info, status, note=None, selected=False):
        mark, fg, bg, label = NODE_STYLE.get(status, NODE_STYLE[None])
        if selected:
            bg = "#dbeafe" if status != "running" else "#e3f2fd"
        info["dot"].config(text=mark, fg=fg)
        info["frame"].config(bg=bg)
        info["body"].config(bg=bg)
        info["title"].config(bg=bg)
        # note 是节点写的全量证据（可能上百字符），步骤行只放**摘要**，
        # 原文在 state.json 与日志里；见 NOTE_MAX / _short_note()。
        info["sub"].config(bg=bg,
                           text=_short_note(note) if note is not None else label)
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

    def set_current(self, sid, name, status, target=None):
        label = {"running": "运行中", "ok": "已完成", "failed": "失败",
                 "timeout": "超时", "skipped": "跳过"}.get(status, status or "")
        scope = ""
        if target:
            scope = f"{dict(TARGET_PROGRAMS).get(target, target)} · "
        self.lbl_current.config(
            text=f"当前步骤 {scope}{sid} · {name} · {label}",
            fg="#1565c0" if status == "running" else
               ("#c62828" if status in ("failed", "timeout") else "#33475b"))

    # state.json 里的状态名 == NODE_STYLE 的键，故只做"过滤未知值"。
    def _vis(self, status):
        return status if status in NODE_STYLE and status is not None else None

    def set_node(self, target, sid=None, status=None, note=None, elapsed=None):
        """记一条节点状态并重画。

        新签名：`set_node(target, sid, status, note)`，`target` = 程序 key，
        None 表示"还不知道是哪个程序"（跟随记录模式下的单目标运行）。
        旧签名 `set_node(sid, status, note)` 仍然认 —— docs/ 下几个自检探针
        直接调它（它们是"界面确实会变"的证据来源），不为改签名去动它们。
        """
        # 旧签名兼容 —— docs/ 下几个自检探针是"界面确实会变"的证据来源，
        # 不为改签名去动它们。可能的旧写法：
        #   set_node(sid, status)             2nd 是状态
        #   set_node(sid, status, note)       2nd 是状态
        #   set_node(sid, name, status, note) 2nd 是名字，3rd 才是状态
        # 新签名的 2nd 参数必是节点号（chain.all_ids()），不会与上面三种混淆。
        if sid not in self._all_sids():
            if sid in NODE_STYLE:
                target, sid, status, note = None, target, sid, status
            else:
                target, sid = None, target
        # 状态挂到"当前显示的程序"下：_repaint_steps/_status_of 按
        # self._scope_key 取，None 桶在按程序建行的视图里看不见。
        if target is None:
            target = self._scope_key
        self._tstate.setdefault(target, {})[sid] = (status, note)
        self._active_target = target
        self._refresh_target_dots()
        self._sync_scope()
        self._repaint_steps()

    def _effective_view_target(self):
        """下面的步骤行该显示哪个目标的进度。"""
        if self._view_target:
            return self._view_target
        if self._active_target is not None:
            return self._active_target
        known = [k for k in self._tstate if k]
        return known[0] if len(known) == 1 else None

    def _target_label(self, tgt):
        if tgt is None:
            return "未确定（跟随 state.json）"
        return dict(TARGET_PROGRAMS).get(tgt, tgt)

    def _repaint_steps(self):
        tgt = self._scope_key
        st = self._tstate.get(tgt) or {}
        for sid, info in self.node_rows.items():
            status, note = st.get(sid, (None, None))
            self._paint(info, self._vis(status), note)
        if hasattr(self, "lbl_scope"):
            self.lbl_scope.config(text=f"步骤状态：{self._target_label(tgt)}")

    def _refresh_target_dots(self):
        """每个目标行尾的进度点：完成数 / 总数 + 聚合状态。"""
        done_states = ("ok", "failed", "timeout", "skipped")
        for key, r in getattr(self, "_target_rows", {}).items():
            total = len(self._ids_of(key))
            st = self._tstate.get(key) or {}
            states = [s for s, _n in st.values()]
            done = sum(1 for s in states if s in done_states)
            if any(s in ("failed", "timeout") for s in states):
                mark, fg = NODE_STYLE["failed"][0], NODE_STYLE["failed"][1]
            elif total and done == total and all(s == "ok" for s in states):
                mark, fg = NODE_STYLE["ok"][0], NODE_STYLE["ok"][1]
            elif "running" in states:
                mark, fg = NODE_STYLE["running"][0], NODE_STYLE["running"][1]
            elif done:
                # 部分完成、没在跑、也没错：只报数字，不加符号 ——
                # 之前用 "…" 前缀，看起来像文本被截断了（实测截图如此）。
                mark, fg = "", "#6d6d6d"
            else:
                mark, fg = NODE_STYLE[None][0], NODE_STYLE[None][1]
            if mark:
                text = f"{mark} {done}/{total}" if done else mark
            else:
                text = f"{done}/{total}"
            r["dot"].config(text=text, fg=fg)

    # ------------------------------------------------------------- 第 2 页

    def on_pick(self, sid):
        if self.editor.is_dirty():
            if not messagebox.askyesno(
                    "未保存", f"节点 {self.selected} 的修改尚未保存。\n"
                              f"放弃修改并切换到节点 {sid}？"):
                return

        self._load_node(sid)
        self._repaint_picks()

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
        tgt = self._scope_key
        return (self._tstate.get(tgt) or {}).get(sid, (None, None))[0]

    # ------------------------------------------------------------- 运行

    def on_run(self):
        if self.runner.is_running():
            return
        if self.editor.is_dirty() and self.selected:
            if not messagebox.askyesno(
                    "未保存", f"节点 {self.selected} 有未保存的修改。\n"
                              f"本次运行不会包含它们。仍要运行？"):
                return

        # 目标程序：勾几个就传几个；「跟随上次记录」则完全不传。
        # "" 必须**不传**（而不是传 "ww"）—— 否则「接着上次」续跑 ok-nte 时
        # 会被悄悄改回 ok-ww（main.py 的 --target 是覆盖语义）。
        picked = []
        if self.follow_var.get():
            tgt = None
        else:
            picked = self.selected_targets()
            if not picked:
                messagebox.showwarning(
                    "目标程序",
                    "没有勾选任何目标程序。\n\n"
                    "勾一个（或点「全选」），或者勾上「跟随上次记录」。")
                return
            tgt = ",".join(picked)

        # 「只跑节点 N」的编号是**每个程序自己的**：勾了多个程序时，
        # N 必须在每一个的链条里都存在，否则 main.py 会直接 SystemExit。
        only = self.only_var.get().strip()
        if only and picked:
            disp = dict(TARGET_PROGRAMS)
            bad = [k for k in picked if only not in self._ids_of(k)]
            if bad:
                messagebox.showwarning(
                    "节点号不适用",
                    f"节点 {only} 不在 "
                    + "、".join(disp.get(k, k) for k in bad)
                    + " 的链条里。\n\n请改选一个这些程序都有的节点，"
                      "或取消「只跑节点」。")
                return

        args = []
        if self.dry_run.get():
            args.append("--dry-run")
        if only:
            args += ["--only", only]
        if self.resume_var.get():
            args.append("--resume")
        if tgt:
            args += ["--target", tgt]
        self._active_args = list(args)

        self.log_text.delete("1.0", "end")
        self._tstate = {}
        self._active_target = None
        self._view_target = None
        self._sync_scope()
        self._refresh_target_dots()
        self._repaint_steps()
        self._set_target_controls(False)
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
        self._set_target_controls(True)
        self.status(f"结束：{note}", "ok" if code == 0 else "err")
        self.append_log(f"\n=== 编排结束：{note}（退出码 {code}）===",
                        "ok" if code == 0 else "err")
        # 结束后再读一次 state.json，把最终状态补齐
        raws = self.watcher.poll() or {}
        for target, raw in raws.items():
            self._apply_final(target, raw)
        # 日志保留：只留最近十轮（orchestrator/logretention.py）。
        # 静默 = 后台线程 + 不弹窗 + 失败不冒泡；清理是附带动作，不该影响
        # "这一轮跑完了没有" 这个结论，也不该让界面卡一下。
        threading.Thread(target=self._sweep_logs, daemon=True).start()

    def _sweep_logs(self):
        """编排结束后静默清理旧运行目录（保留策略见 orchestrator/logretention.py）。"""
        try:
            from orchestrator import logretention
            rep = logretention.sweep_silently()
        except Exception:                   # noqa: BLE001 —— 见上：不该冒泡
            return
        if rep and rep.get("deleted"):
            self.bus.log("[GUI] 日志保留：清理 %d 个旧运行目录（保留最近 %d 轮）"
                         % (len(rep["deleted"]), rep.get("keep", 0)))

    def _apply_final(self, target, raw):
        for sid, rec in (raw.get("steps") or {}).items():
            st = rec.get("status")
            if st and st != "running":
                note = (rec.get("notes") or [None])[-1]
                self.set_node(target, sid, st, note)
        last = raw.get("last_step")
        if last and last in self._ids_of(target):
            self.set_node(target, last, raw.get("last_status") or "ok")

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
                    target, sid, name, status, note, elapsed = payload
                    # state.json 的状态名 -> 界面状态名
                    vis = self._vis(status)
                    self.set_node(target, sid, vis, note)
                    if status == "running":
                        row = self._node_row(target, sid)
                        if row is None:
                            row = self._node_row(self._scope_key, sid)
                        shown = row[1] if row else name
                        self.set_current(sid, shown, "running", target=target)
                elif kind == "finished":
                    self.on_finished(*payload)
                elif kind == "status":
                    self.status(*payload)
        except queue.Empty:
            pass

        # 轮询 state.json（运行中才需要）。节点状态由 StateWatcher 推，
        # 这里只兜住"最后一条状态没推送出来"的情况。
        if self.runner.is_running() and self.watcher.run_dir:
            raws = self.watcher.poll() or {}
            for target, raw in raws.items():
                last = raw.get("last_step")
                if (last and last in self._ids_of(target)
                        and raw.get("last_status")):
                    self.set_node(target, last, raw["last_status"])

        if self.nb.index(self.nb.select()) == 1:
            self._refresh_save_buttons()
        self.after(120, self._pump)

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
        """各程序节点清单与磁盘比对。**警告，不崩溃** —— GUI 必须在链条坏掉时还能开。"""
        problems = chain.verify_against_disk()
        if not problems:
            self.status("就绪 — 各程序的节点清单与磁盘一致", "ok")
        else:
            self.status(f"⚠ 节点清单有 {len(problems)} 处问题（见日志）", "warn")
            for p in problems:
                self.append_log(f"[警告] {p}", "warn")
            self.append_log("", "plain")
            self.append_log("[提示] 以上问题不影响 GUI 打开与改代码；"
                            "但运行编排前应先修好。", "warn")
        # 目标清单同样"警告不崩溃"：读不出 programs.py 时界面上仍有兜底项，
        # 但必须让人知道兜底了 —— 否则会以为勾的就是真的。
        for p in TARGET_PROBLEMS:
            self.append_log(f"[警告] 目标程序清单：{p}", "warn")
        if TARGET_PROBLEMS:
            self.status(f"⚠ 目标清单有 {len(TARGET_PROBLEMS)} 处问题（见日志）",
                        "warn")

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
