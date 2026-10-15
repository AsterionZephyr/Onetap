"""nte_verdict.py — ok-nte 终态判据（Q2 交付物）

## 与 ok-ww 的关键差异

| 项 | ok-ww | ok-nte |
| --- | --- | --- |
| 阶段标记 | `info_set current task <phase>` | **无实质阶段**（只有 wait/in main/None） |
| **终止标记** | `ok:quit app`（进程级） | **`TaskExecutor:Successfully Executed Task, Exiting Game and App!`** |
| 逐任务结果 | 无 | **`DailyRoutineTask:success/failed/skipped: [...]`** |
| 目标游戏 | `Client-Win64-Shipping.exe` | **`HTGame.exe`** |

⇒ **判据不同，必须分开实现**（不能复用 ww_verdict 的阶段序列法）。

## 关键标记（实测自 ok-script.2026-10-02.log）

  任务完成（逐项）  : `TaskExecutor DailyRoutineTask:任务完成: <任务名>`
  任务失败（逐项）  : `TaskExecutor DailyRoutineTask:任务失败: <任务名>`
  汇总              : `DailyRoutineTask:success: [...] failed: [...] skipped: [...]`
  日常结束          : `DailyRoutineTask:结束执行日常任务`
  **★ 终止标记**     : `TaskExecutor:Successfully Executed Task, Exiting Game and App!`
  关闭游戏          : `process:Killing process(es) ... HTGame.exe`

## 判定（**只看是否完成，不看单项成败**）

  用户要求：ok-nte 的单项失败与本项目无关；**运行逻辑只关注是否完成**。
  故单项失败不改判定，仅在完成后**打印失败原文**。

  SUCCESS      : 出现 ★ 终止标记，**或**出现「结束执行日常任务」
  NO_TASK      : 无任何任务痕迹
  RUNNING      : 无终止标记且进程在运行
  UNKNOWN      : 其他（证据不足不报成功）

  （单项失败通过 `extraction_failures()` / `extraction_summary()` 单独取出打印）
"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-nte\data\apps\ok-nte\working\logs")

TERMINAL_MARK = r"TaskExecutor:Successfully Executed Task, Exiting Game and App!"
DAILY_END = r"DailyRoutineTask:结束执行日常任务"
SUMMARY = r"DailyRoutineTask:success:\s*(\[[^\]]*\])\s*failed:\s*(\[[^\]]*\])\s*skipped:\s*(\[[^\]]*\])"
ITEM_DONE = r"DailyRoutineTask:任务完成:\s*(.+)"
ITEM_FAIL = r"DailyRoutineTask:任务失败:\s*(.+)"
KILL_GAME = r"Trying to kill the exe \{[^}]*HTGame\.exe"


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def split_runs(text):
    """按 `ok:quit app` 切分多次运行。

    ⚠️ **不可靠**：若一次运行被**外部强制终止**（如编排的兜底清理），
    它不会写 `ok:quit app`，导致**相邻两次运行被合并成一段** ——
    实测发生过：ok-script.log 从 01:24 到 02:43 被当成一段，
    使新一次运行**借用了上一次运行的成功汇总**（假阳性）。

    ⇒ 编排层判定"本次运行"应优先使用 **`RunWindow`（按文件偏移切窗口）**，
      而不是依赖本函数。本函数仅用于历史日志分析。
    """
    parts = re.split(r"ok:quit app", text)
    segs = []
    n = len(parts)
    for i, seg in enumerate(parts):
        if seg.strip():
            segs.append({"text": seg, "finished": i < n - 1, "index": i})
    return segs


class RunWindow:
    """以**文件偏移**界定"本次运行"的文本窗口（可靠做法）。

    用法:
        w = RunWindow(); w.mark()        # 运行开始前调用
        ...
        v, ev = w.verdict()              # 只看本次新增的日志

    原理：记录运行开始时各日志文件的字节偏移；之后只读取**新增部分**。
    这样无论上一次运行是否正常收尾（有无 `ok:quit app`），都不会串味。
    """

    def __init__(self):
        self.base = {}
        for p in LOGDIR.glob("ok-script*.log"):
            try:
                self.base[p.name] = p.stat().st_size
            except OSError:
                pass
        self._buf = []

    def poll(self):
        """读取新增内容并累积，返回本次新增文本。"""
        chunks = []
        for p in sorted(LOGDIR.glob("ok-script*.log")):
            name = p.name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            prev = self.base.get(name)
            if prev is None:
                # 运行期间新出现的文件（如日志轮转产物）=> 整体算作新增
                chunks.append(read(p))
                self.base[name] = size
            elif size > prev:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(prev)
                    chunks.append(f.read())
                self.base[name] = size
            elif size < prev:
                chunks.append(read(p))
                self.base[name] = size
        c = "\n".join(chunks)
        if c:
            self._buf.append(c)
        return c

    def text(self):
        return "\n".join(self._buf)

    def verdict(self, still_running=False):
        """对**本次新增日志**判定（不再做运行分段 —— 窗口本身已是本次运行）。"""
        return verdict_from_log(self.text(), still_running=still_running,
                                latest_only=False)


def current_run_text(text):
    segs = split_runs(text)
    return segs[-1]["text"] if segs else text


def _list(s):
    return [x.strip().strip("'\"") for x in s.strip("[]").split(",") if x.strip()]


def verdict_from_log(text, still_running=False, latest_only=True):
    """返回 (verdict, evidence[])。"""
    if not text.strip():
        return "UNKNOWN", ["日志为空"]
    if latest_only:
        text = current_run_text(text)
        if not text.strip():
            return "UNKNOWN", ["最后一段运行为空"]

    ev = []
    terminal = bool(re.search(TERMINAL_MARK, text))
    daily_end = bool(re.search(DAILY_END, text))
    killed = bool(re.search(KILL_GAME, text, re.I))

    done_items = re.findall(ITEM_DONE, text)
    fail_items = re.findall(ITEM_FAIL, text)

    m = re.search(SUMMARY, text, re.S)
    succ = fail = skip = None
    if m:
        succ, fail, skip = _list(m.group(1)), _list(m.group(2)), _list(m.group(3))
        ev.append(f"汇总 success={succ} failed={fail} skipped={skip}")
    else:
        ev.append(f"逐项: 完成 {len(done_items)} 项 {done_items[-6:]}, 失败 {len(fail_items)} 项 {fail_items[-4:]}")

    ev.append(f"终止标记={terminal} 日常结束={daily_end} 杀游戏={killed}")

    if not (done_items or fail_items or terminal or daily_end):
        if still_running:
            return "RUNNING", ev + ["尚无任务痕迹，进程在运行"]
        return "NO_TASK", ev + ["无任务痕迹"]

    # 判定只看「是否完成」——个别任务失败不影响流程判定（用户要求）：
    #   ok-nte 的单项失败与本项目无关，仍视为「已完成」，
    #   失败详情另行打印（见 orchestrator 的 print_failures）。
    if terminal:
        return "SUCCESS", ev + ["出现终止标记（进程收尾）"]
    if daily_end:
        return "SUCCESS", ev + ["日常任务结束"]

    if still_running:
        return "RUNNING", ev + ["仍在运行"]

    return "UNKNOWN", ev + ["序列不完整且无终止标记"]


def extraction_failures(text, latest_only=True):
    """提取失败项原文，供完成后打印（不参与判定）。

    ⚠️ 默认 `latest_only=True`：只取**最后一段运行**。
    一个日志文件会累积多次运行（实测 1~4 段），
    若扫描整文件，会把历史运行的失败混进本次。
    """
    if latest_only:
        text = current_run_text(text)
    out = []
    m = re.search(SUMMARY, text, re.S)
    if m:
        out.extend(_list(m.group(2)))
    out.extend(x.strip() for x in re.findall(ITEM_FAIL, text))
    # 去重保序
    seen, uniq = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def extraction_summary(text, latest_only=True):
    """返回 (success, failed, skipped) 三个列表（可能为 None）。"""
    if latest_only:
        text = current_run_text(text)
    m = re.search(SUMMARY, text, re.S)
    if not m:
        return None, extraction_failures(text, latest_only=False), None
    return _list(m.group(1)), _list(m.group(2)), _list(m.group(3))


class LogWatcher:
    """跟踪 ok-nte 日志的**本次运行**内容（以文件偏移界定）。

    ⚠️ 早期版本在构造时 `read()` 读入**全部历史日志**，再按 `ok:quit app` 分段取最后一段。
    该做法有**假阳性**：若上一次运行被**外部强制终止**（编排的兜底清理就是），
    它不会写 `ok:quit app`，两次运行被**合并成一段** ——
    实测导致新一次运行在点击后 **1 秒**就报 SUCCESS（借用了上一次的汇总）。

    ⇒ 现在只记录**基线字节偏移**，`accumulated()` 只返回运行开始后**新增**的内容。
    """

    def __init__(self):
        self._seen = {}
        self._buf = []
        self._baseline = {}
        for p in LOGDIR.glob("ok-script*.log"):
            try:
                self._baseline[p.name] = p.stat().st_size
                self._seen[p.name] = p.stat().st_size
            except OSError:
                pass

    def poll(self):
        chunks = []
        for p in sorted(LOGDIR.glob("ok-script*.log")):
            name = p.name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            prev = self._seen.get(name)
            if prev is None:
                # 运行期间新出现的文件（日志轮转产物）=> 整体算作新增
                chunks.append(read(p))
                self._seen[name] = size
            elif size > prev:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(prev)
                    chunks.append(f.read())
                self._seen[name] = size
            elif size < prev:
                chunks.append(read(p))
                self._seen[name] = size
        c = "\n".join(chunks)
        if c:
            self._buf.append(c)
        return c

    def accumulated(self):
        """**本次运行**新增的日志（不含历史）。"""
        return "\n".join(self._buf)

    def text(self):
        return self.accumulated()


def main():
    print("=" * 76)
    print("ok-nte 终态判据")
    print("=" * 76)
    files = sorted(LOGDIR.glob("ok-script*.log"))
    print(f"\n{'文件':<28} {'整文件':<14} {'最后一段':<14} 段数")
    print("-" * 76)
    for f in files:
        raw = read(f)
        va, _ = verdict_from_log(raw, latest_only=False)
        vl, _ = verdict_from_log(raw, latest_only=True)
        print(f"{f.name:<28} {va:<14} {vl:<14} {len(split_runs(raw))}")

    p = max(files, key=lambda x: x.stat().st_size)
    v, ev = verdict_from_log(read(p), latest_only=False)
    print(f"\n最大日志 {p.name} => {v}")
    for e in ev:
        print(f"    {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
