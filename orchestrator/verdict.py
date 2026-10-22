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

# 终态常量（与 orchestrator 侧一致，便于比较）。
# 定义在无依赖的叶子模块里：apps/*.py 的判据要用同一批字符串，而它们
# **不允许** import 本文件（会循环）。见 orchestrator/statuses.py 的说明。
from . import programs as programs_mod
from .statuses import FAILED, NO_TASK, RUNNING, SUCCESS, UNKNOWN  # noqa: E402,F401


def logdir_self_check(program=None):
    """校验日志目录真实存在（防止「路径写错 ⇒ 永远读空 ⇒ 静默失效」）。

    返回问题字符串列表；空列表表示正常。
    这条断言是有来历的：`_logdir_for` 初版把目录名写成 `ok-<key>` 漏了
    `ok-` 前缀，得到不存在的 `...\\apps\\ww\\working\\logs`，
    而 `LogWindow` 对此**不报错**，只是恒返回 RUNNING/UNKNOWN。
    """
    from . import programs as programs_mod

    progs = [programs_mod.get(program)] if program is not None else list(programs_mod.ALL)
    problems = []
    for p in progs:
        d = _logdir_for(p)
        # 文件名**按程序给出**（Program.log_glob）：MaaEnd 的日志是
        # mxu-tauri.log，用 ok-script*.log 去 glob 它的目录必然为空 ⇒
        # 假问题（「日志目录里没有 ok-script*.log」），反而掩盖真问题。
        # ok-ww / ok-nte 的默认值仍是 ok-script*.log，行为不变。
        pat = getattr(p, "log_glob", None) or "ok-script*.log"
        if not Path(d).exists():
            problems.append(f"{p.key}: 日志目录不存在 {d}")
        elif not list(Path(d).glob(pat)):
            problems.append(f"{p.key}: 日志目录里没有 {pat} ({d})")
    return problems


def _key_of(program):
    """把 program 参数（Program 实例 / key 字符串 / None）归一成 key。"""
    if program is None:
        return None
    key = getattr(program, "key", program)
    return str(key)


def _logdir_for(program):
    """按目标程序给出日志目录（FAULT #15：两程序目录不同）。

    ⚠️ 目录名是 `ok-<key>`（`ok-ww` / `ok-nte`），**不是** `<key>`。
    实测若写成 `<key>` 会得到 `...\\apps\\ww\\working\\logs` 这种**不存在的路径**，
    `LogWindow` 于是永远读到空日志 ⇒ 恒报 RUNNING/UNKNOWN ⇒ **静默失效**。
    故这里显式登记，并允许用 Program 上的 `logdir` 覆盖。
    """
    from . import programs as programs_mod

    prog = programs_mod.get(program) if not hasattr(program, "key") else program
    override = getattr(prog, "logdir", None)
    if override:
        return Path(override)
    return Path(prog.root_dir) / "data" / "apps" / f"ok-{prog.key}" / "working" / "logs"


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

    def __init__(self, logdir=None, program=None):
        """logdir 优先；否则按 program 选对应程序的日志目录；默认 ok-nte。

        ⚠️ 两个程序的日志目录**不同**（`...\\ok-ww\\...\\logs` 与
        `...\\ok-nte\\...\\logs`）。若只认 ok-nte 的目录，
        对 ok-ww 跑判据会永远读到「空日志」⇒ 恒返回 RUNNING/UNKNOWN，
        **静默失效**（不报错，只是永远判不出来）。
        """
        if logdir is None:
            # 未指定程序时默认 ok-nte（历史行为）；指定了就走 _logdir_for，
            # 它会尊重 Program.logdir 覆盖（MaaEnd 的 debug/ 目录）。
            logdir = _logdir_for(program if program is not None else programs_mod.NTE)
        self.logdir = Path(logdir)
        self._seen = {}
        self._buf = []
        self._program = program
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

    def verdict(self, still_running=False, program=None):
        prog = program or self._program
        from . import apps as apps_mod

        if prog is not None and _key_of(prog) == "ww":
            return apps_mod.get("ww").ww_verdict(self.text(), still_running=still_running)
        return apps_mod.get("nte").nte_verdict(self.text(), still_running=still_running)

    def failures(self):
        from . import apps as apps_mod

        return apps_mod.get("nte").nte_failures(self.text())


def verdict_for(program=None, text=None, still_running=False, log_window=None):
    """按**目标程序**分派判据。

    三个程序**都**走日志判据（FAULT #15 更正了 ok-ww 的旧结论）：
      - ok-nte ⇒ `nte_verdict`（额外有逐项汇总 success/failed/skipped）
      - ok-ww  ⇒ `ww_verdict`（只有终止标记与阶段行，无逐项汇总）
      - MaaEnd(zmd) ⇒ `zmd_verdict`（mxu-tauri.log；唯一判据是 stop_agent_impl，
        且**必须**过 ZmdLogWindow 的时间戳闸，否则会借到上一次运行的完成信号）

    ⚠️ zmd 的 log_window **必须**是 ZmdLogWindow。传一个通用 LogWindow 进来
    不会报错（`LogWindow.verdict(still_running, program=None)` 的 program 有
    默认值，照样调用成功），但它没有时间戳闸 ⇒ 会借到上一次运行的 stop，
    而「上一轮有 stop」正是 MaaEnd 侧唯一的假成功来源。故 zmd 分支**显式**
    做 isinstance 校验，宁可抛 TypeError 也不静默降级（INV-30 的同一精神）。

    仍保留「未知程序显式抛错」的纪律 —— 不回落默认，
    避免「以为在判定 A 实际判定了 B」这种静默错配。
    """
    from . import programs as programs_mod

    prog = programs_mod.get(program)
    from . import apps as apps_mod

    if prog.key == "nte":
        if log_window is not None:
            return log_window.verdict(still_running=still_running)
        return apps_mod.get("nte").nte_verdict(text or "", still_running=still_running)

    if prog.key == "ww":
        if log_window is not None:
            return log_window.verdict(still_running=still_running, program=prog)
        return apps_mod.get("ww").ww_verdict(text or "", still_running=still_running)

    if prog.key == "zmd":
        if log_window is not None:
            # 只认 ZmdLogWindow：通用 LogWindow 的 verdict(still_running, program=None)
            # 也能调用成功，但它**没有时间戳闸**（MaaEnd 每次启动会清日志、
            # 删旧日志，只按字节偏移会借到上一次运行的 stop_agent_impl ⇒ 假成功）。
            # 故显式校验类型，误用时立刻 TypeError，绝不静默降级。
            if not isinstance(log_window, ZmdLogWindow):
                raise TypeError(
                    f"MaaEnd 的终态判据只接受 ZmdLogWindow（带时间戳闸），"
                    f"收到的是 {type(log_window).__name__}。"
                )
            return log_window.verdict(still_running=still_running)
        return zmd_verdict(text or "", still_running=still_running)

    raise ValueError(f"没有为 {prog.key} 实现终态判据；请勿回落默认值。")

# ==========================================================================
# MaaEnd（zmd）的运行判据**已迁到** orchestrator/apps/zmd/（docs/adr/0003）
# ==========================================================================
# 这里保留 re-export 垫片：verdict_for / probe/*selfcheck 的
# 旧调用点行为完全不变。**新增或修改 MaaEnd 的判据请改 apps/zmd/。**
# 私有辅助也一并转出：probe/zmd_verdict_selfcheck.py 直接用 _zmd_hits 数证据行
# （垫片的目的就是「旧调用点不用改」，私有名字同样适用）。
from .apps.zmd import (  # noqa: E402,F401  (re-export)
    _ANSI_RE,
    _ZMD_START_MARK_RX,
    _ZMD_STOP_MARK_RX,
    _ZMD_TS_RE,
    _zmd_clean,
    _zmd_ev,
    _zmd_hits,
    _zmd_last_ts,
    _zmd_log_path,
    _zmd_read_tail,
    ZMD_AGENT_ERR,
    ZMD_KILL_GAME,
    ZMD_LOGDIR,
    ZMD_LOG_NAME,
    ZMD_PRETASK_FAIL,
    ZMD_SELFCHECK_BYTES,
    ZMD_START_MARK,
    ZMD_STOP_MARK,
    ZMD_STOP_SOFT,
    ZmdLogWindow,
    zmd_filter_since,
    zmd_log_self_check,
    zmd_parse_ts,
    zmd_verdict,
)


# ---------------------------------------------------------------------------
# 旧调用点垫片（PEP 562）：名字按归属转出到 apps/<key>.py。
# 同 match.py 的理由 —— apps/<key>.py 模块级 import 本模块，这里若也模块级
# import apps 就会成环，故只在**取属性时**惰性转出。
# ---------------------------------------------------------------------------
_EXPORT_OWNER = {
    "ww": (
        "WW_DAILY_END",
        "WW_KILL_GAME",
        "ww_verdict",
    ),
    "nte": (
        "NTE_DAILY_END",
        "NTE_EXECUTOR_PAUSE",
        "NTE_ITEM_DONE",
        "NTE_ITEM_FAIL",
        "NTE_KILL_GAME",
        "NTE_LOGDIR",
        "NTE_SUMMARY_NEW",
        "NTE_SUMMARY_OLD",
        "NTE_TERMINAL_MARK",
        "_NTE_BIZ_RE",
        "_NTE_EXIT_RE",
        "_NTE_NOISE_RE",
        "_as_list",
        "nte_executor_paused",
        "nte_failures",
        "nte_verdict",
        "parse_nte_summary",
    ),
}


def __getattr__(name):
    for _key, _names in _EXPORT_OWNER.items():
        if name in _names:
            from . import apps as apps_mod

            return getattr(apps_mod.get(_key), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
