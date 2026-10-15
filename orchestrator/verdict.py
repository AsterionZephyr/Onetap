"""orchestrator.verdict — 终态判据（按目标程序分派）

## 为什么需要「判据」这一层

编排跑完点击后，必须回答一个问题：**任务到底完成了没有？**
两个程序给出答案的方式**完全不同**（FRAMEWORK §0.1），故判据必须分开实现：

| 项 | ok-ww | ok-nte |
| --- | --- | --- |
| 判定依据 | **画面**（完成帧 `exit_notice`） | **日志**（终止标记） |
| 阶段标记 | `info_set current task <phase>` | 无实质阶段 |
| 终止标记 | `ok:quit app`（进程级） | `TaskExecutor:Successfully Executed Task, Exiting Game and App!` |
| 逐任务结果 | 无 | `DailyRoutineTask:info_set success/failed/skipped [...]` |
| 目标游戏 | `Client-Win64-Shipping.exe` | `HTGame.exe` |

**ok-ww 侧的已知缺口**：`exit_notice` 图像**从未采集**，缺失时框架
「无法判定正常完成，只能以超时收场」。那是 ok-ww 唯一的判据缺口。
ok-nte 侧反而**不需要图像** —— 它把终态写进日志，比看图可靠得多。

## 本模块只做 ok-nte（日志判据）

ok-ww 的判据在 `orchestrator/orchestrator.py` 里（完成帧 + 阶段序列），
本次**不动它**，避免回归。

## ⚠️ 三条来之不易的实测教训（都体现在代码里）

1. **不能用「按 `ok:quit app` 分段取最后一段」来界定本次运行。**
   若上一次运行被**外部强制终止**（编排的兜底清理就是这种情况），
   它不会写 `ok:quit app` ⇒ 相邻两次运行被**合并成一段** ⇒
   新一次运行**借用上一次的成功汇总** —— 实测在点击后 **1 秒**就报 SUCCESS
   （假阳性）。故必须用 `LogWindow`（**按文件字节偏移**切窗口）。

2. **正则会被程序升级悄悄打死**（FAULT #18）。ok-nte v1.4.8 把汇总行从
   「一行三段」改成「三行独立 `info_set`」，老正则变成匹配不到，
   `success`/`skipped` 静默变 `None`、`failed` 静默变 `[]`。
   ⇒ 两种格式都认，且失配时**显式警示**，绝不当成「没有失败」。

3. **单项失败不改变终态判定**（用户明确要求）：
   ok-nte 的个别任务失败与本项目无关，**只看是否完成**；
   失败详情另行取出打印，不参与判定。
"""

import re
from pathlib import Path

# --- ok-nte 关键标记（实测自真日志）----------------------------------------

# ★ 终止标记：进程收尾，**最强的完成证据**
NTE_TERMINAL_MARK = (
    r"TaskExecutor:Successfully Executed Task, Exiting Game and App!")

# 日常任务结束
NTE_DAILY_END = r"DailyRoutineTask:结束执行日常任务"

# 逐项结果
NTE_ITEM_DONE = r"DailyRoutineTask:任务完成:\s*(.+)"
NTE_ITEM_FAIL = r"DailyRoutineTask:任务失败:\s*(.+)"

# 关闭游戏（HTGame.exe —— 与 ok-ww 的 Client-Win64-Shipping.exe 不同）
NTE_KILL_GAME = r"Trying to kill the exe \{[^}]*HTGame\.exe"

# 日志目录
NTE_LOGDIR = Path(
    r"E:\TOOLS\ScriptsGames\ok-nte\data\apps\ok-nte\working\logs")

# --- 汇总行的两种格式（FAULT #18）------------------------------------------
#
# **新格式**（ok-nte v1.4.8 起）——三行独立，带 `info_set` 前缀，关键字后**无冒号**：
#     DailyRoutineTask:info_set success ['异象界域', ...]
#     DailyRoutineTask:info_set failed []
#     DailyRoutineTask:info_set skipped ['异象追猎']
NTE_SUMMARY_NEW = (
    r"DailyRoutineTask:info_set success\s*(\[[^\]]*\])"
    r"\s*\n.*?DailyRoutineTask:info_set failed\s*(\[[^\]]*\])"
    r"\s*\n.*?DailyRoutineTask:info_set skipped\s*(\[[^\]]*\])")
#
# **老格式**（≤ v1.4.7）——同一行三段，关键字后**有冒号**：
#     DailyRoutineTask:success: ['甲', '乙']\nfailed: []\nskipped: []
NTE_SUMMARY_OLD = (
    r"DailyRoutineTask:success:\s*(\[[^\]]*\])"
    r"\s*failed:\s*(\[[^\]]*\])"
    r"\s*skipped:\s*(\[[^\]]*\])")

# 终态常量（与 orchestrator 侧一致，便于比较）
SUCCESS = "success"
FAILED = "failed"
UNKNOWN = "unknown"
NO_TASK = "no_task"
RUNNING = "running"


def _as_list(s):
    """把 `['甲', '乙']` 这样的字面量解析成列表。

    ⚠️ 不是 JSON —— 实测日志里用的是**单引号**，故 `json.loads` 会失败。
    这里做的是**逐项剥离引号**，与 probe 侧 `_list` 行为一致。
    """
    return [x.strip().strip("'\"") for x in s.strip("[]").split(",") if x.strip()]


def parse_nte_summary(text):
    """取 ok-nte 汇总行的 (success, failed, skipped) 三个列表。

    **先试新格式、再退老格式**；都不中 ⇒ `(None, None, None)`。

    ⚠️ **要么三段都给，要么三段都给 None**。老实现在失配时返回
    `(None, <失败项>, None)`，其中 `failed` 看似是正确的空列表，
    实则只是「恰好没失败」—— 真失败时同样表现为「没有失败」，无从察觉。
    调用方拿到全 None 时**必须警示**，不得当成「没有失败」。
    """
    for pat in (NTE_SUMMARY_NEW, NTE_SUMMARY_OLD):
        m = re.search(pat, text, re.S)
        if m:
            return _as_list(m.group(1)), _as_list(m.group(2)), _as_list(m.group(3))
    return None, None, None


def nte_failures(text):
    """取出失败项原文（**不参与判定**，仅用于完成后打印）。"""
    succ, fail, skip = parse_nte_summary(text)
    out = list(fail) if fail else []
    out.extend(x.strip() for x in re.findall(NTE_ITEM_FAIL, text))
    seen, uniq = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def nte_verdict(text, still_running=False):
    """对 ok-nte 的日志文本判定终态。返回 (verdict, evidence[])。

    判定只看**是否完成**：

        SUCCESS  : 出现终止标记，**或**出现「结束执行日常任务」
        RUNNING  : 无终止标记且进程仍在运行
        NO_TASK  : 无任何任务痕迹
        UNKNOWN  : 其他（**证据不足绝不报成功**，INV-30）
    """
    if not text or not text.strip():
        return UNKNOWN, ["日志为空（本次运行尚无新增内容）"]

    ev = []
    terminal = bool(re.search(NTE_TERMINAL_MARK, text))
    daily_end = bool(re.search(NTE_DAILY_END, text))
    killed = bool(re.search(NTE_KILL_GAME, text, re.I))

    done_items = re.findall(NTE_ITEM_DONE, text)
    fail_items = re.findall(NTE_ITEM_FAIL, text)

    succ, fail, skip = parse_nte_summary(text)
    if succ is not None or fail is not None or skip is not None:
        ev.append(f"汇总 success={succ} failed={fail} skipped={skip}")
    else:
        # FAULT #18：必须说出来。两种可能 ——
        #   (a) 日志里确实没有汇总行（早退 / 崩溃）；
        #   (b) **程序升级又改了格式**（老正则就是这样死的）。
        # 无论哪种，都**不能**静默当成「没有失败」。
        ev.append(f"[!] 未解析到汇总行（格式可能又变了）："
                  f"逐项 完成 {len(done_items)} 项 {done_items[-6:]}, "
                  f"失败 {len(fail_items)} 项 {fail_items[-4:]}")

    ev.append(f"终止标记={terminal} 日常结束={daily_end} 杀游戏={killed}")

    if not (done_items or fail_items or terminal or daily_end):
        if still_running:
            return RUNNING, ev + ["尚无任务痕迹，进程在运行"]
        return NO_TASK, ev + ["无任务痕迹"]

    if terminal:
        return SUCCESS, ev + ["出现终止标记（进程收尾）"]
    if daily_end:
        return SUCCESS, ev + ["日常任务结束"]

    if still_running:
        return RUNNING, ev + ["仍在运行"]

    return UNKNOWN, ev + ["序列不完整且无终止标记"]


class LogWindow:
    """以**文件字节偏移**界定「本次运行」的日志窗口。

    ## 为什么不能按 `ok:quit app` 分段

    若上一次运行被**外部强制终止**（本框架的兜底清理就会这么做），
    它不会写 `ok:quit app` ⇒ 相邻两次运行**合并成一段** ⇒
    新一次运行**借用上一次的成功汇总**，实测在点击后 **1 秒**就报 SUCCESS。
    按**字节偏移**切窗口则与上一次如何收尾**无关**。

    用法::

        w = LogWindow(); w.mark()      # 运行开始前
        ...                            # 跑任务
        v, ev = w.verdict()            # 只看本次新增的日志
    """

    def __init__(self, logdir=None):
        self.logdir = Path(logdir or NTE_LOGDIR)
        self._seen = {}
        self._buf = []
        self.mark()

    def mark(self):
        """记录当前各日志文件的字节偏移作为基线。"""
        self._seen = {}
        for p in self._files():
            try:
                self._seen[p.name] = p.stat().st_size
            except OSError:
                pass

    def _files(self):
        try:
            return sorted(self.logdir.glob("ok-script*.log"))
        except OSError:
            return []

    def poll(self):
        """读取**新增**内容并累积，返回本次新增文本。

        ⚠️ 三种情形都要处理（否则会漏读或重读）：
          - 文件**新出现**（日志轮转产物）⇒ 整体算作新增
          - 文件**变大** ⇒ 从旧偏移读到尾
          - 文件**变小**（被轮转/截断）⇒ **整体重读**，不能只读差值
        """
        chunks = []
        for p in self._files():
            name = p.name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            prev = self._seen.get(name)
            if prev is None:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    chunks.append(f.read())
                self._seen[name] = size
            elif size > prev:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(prev)
                    chunks.append(f.read())
                self._seen[name] = size
            elif size < prev:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    chunks.append(f.read())
                self._seen[name] = size
        c = "\n".join(chunks)
        if c:
            self._buf.append(c)
        return c

    def text(self):
        """**本次运行**累积的新增日志（不含历史）。"""
        return "\n".join(self._buf)

    def verdict(self, still_running=False):
        return nte_verdict(self.text(), still_running=still_running)

    def failures(self):
        return nte_failures(self.text())


def verdict_for(program=None, text=None, still_running=False, log_window=None):
    """按**目标程序**分派判据。

    ok-nte ⇒ 日志判据（本模块）。ok-ww ⇒ **不走这里**
    （它用画面完成帧，见 orchestrator.py），故显式拒绝，
    避免「以为在用日志判定 ok-ww」这种**静默的错配**。
    """
    from . import programs as programs_mod

    prog = programs_mod.get(program)
    if prog.key == "nte":
        if log_window is not None:
            return log_window.verdict(still_running=still_running)
        return nte_verdict(text or "", still_running=still_running)

    raise ValueError(
        f"{prog.display} 的终态判据**不是日志判据**"
        f"（它用画面完成帧 exit_notice，见 orchestrator.py）。"
        f"请勿把 verdict_for 用于 {prog.key}。")
