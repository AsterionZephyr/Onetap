"""ww_verdict.py — ok-ww 终态判据（基于日志，Q1 交付物）

依据：对 8 份历史日志的实测对比（见 ww_completion_signal.py）。

## 实测结论

**不可用的信号**：
  - `exit_event.is_set`：8 份中仅 2 份 is_set，而 6 份 is not set 的同样跑完了任务序列。
    => 它只反映"关窗路径"，**不能判成功**。

**可靠信号 = 任务阶段序列走到了哪些步骤**。
`DailyTask:info_set current task <X>` 的完整序列（实测全集）：
    wait main esc=True      （等待，非阶段）
    in main esc=True        （就绪，非阶段）
    claim daily             <- 领日常
    claim mail              <- 领邮件
    check weekly garden     <- 检查周本花园
    check discarded echo    <- 检查废弃声骸  ★ 最完整运行的收尾步骤

**终止标记**：`MainThread ok:quit app`（始终是最后一行）

**中断特征**：`<...DailyTask...> is disabled, raise Exception` + `TaskDisabledException, continue`
    -> 实测：一次运行走到 `claim mail` 后触发此异常并退出（非正常收尾）。

## 判据

    SUCCESS      : 到达 check weekly garden / check discarded echo（完整收尾）
    SUCCESS_PART : 到达 claim mail 但未到 check *（部分完成）
    PARTIAL      : 只到 claim daily
    FAILED       : 出现 TaskDisabledException 且未达 claim mail
    NO_TASK      : 日志无任务痕迹
    RUNNING      : 无终止标记且进程仍在
    UNKNOWN      : 其他
"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs")

# 阶段全集（实测）
PHASE_ORDER = ["claim daily", "claim mail", "check weekly garden", "check discarded echo"]
FULL_FINAL = ["check weekly garden", "check discarded echo"]


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def task_sequence(text):
    """提取 current task 的变化序列（去重相邻）。

    ⚠️ 阶段可能来自**不同的任务类**（实测有 DailyTask / GardenTask / MergeEchoTask），
    故用通用前缀 `TaskExecutor \\w+Task:info_set current task`，而非只匹配 DailyTask。
    """
    seq = re.findall(r"TaskExecutor \w*Task:info_set current task (.+)", text)
    out = []
    for s in seq:
        s = s.strip()
        if not out or out[-1] != s:
            out.append(s)
    return out


def split_runs(text):
    """按 `ok:quit app` 把一个日志文件切成多次运行。

    必要性：`ok-script.log` 会**累积多次运行**（实测含 3 段）。
    若不分段，上一次运行的成功阶段会被算到本次头上 —— **假阳性**。

    返回 [RunSegment, ...]，每段含 text / finished / index。
    """
    parts = re.split(r"ok:quit app", text)
    segs = []
    n = len(parts)
    for i, seg in enumerate(parts):
        # split 后，第 i 段之后紧跟一个 quit app（除最后一段外）=> 该段是"已结束的运行"
        finished = (i < n - 1)
        if seg.strip():
            segs.append({"text": seg, "finished": finished, "index": i})
    return segs


def current_run_text(text):
    """取**当前（最后一次）运行**的内容。

    规则：
      - 若最后一段以 quit app 结束（无内容残留），则当前运行 = 最后一个非空段
      - 否则当前运行 = 最后一个非空段（尚未结束）
    即：**始终取最后一个非空段**。
    """
    segs = split_runs(text)
    return segs[-1]["text"] if segs else text


def verdict_from_log(text, still_running=False, latest_only=True):
    """返回 (verdict, evidence[])。

    latest_only=True（默认）：**只取最后一段运行**，避免把历史运行的成功算到本次头上。
    """
    if not text.strip():
        return "UNKNOWN", ["日志为空"]

    if latest_only:
        text = current_run_text(text)
        if not text.strip():
            return "UNKNOWN", ["最后一段运行为空"]

    seq = task_sequence(text)
    reached = [p for p in PHASE_ORDER if p in seq]
    quit_app = bool(re.search(r"ok:quit app", text))
    disabled = bool(re.search(r"is disabled, raise Exception", text))
    killed = bool(re.search(r"Trying to kill the exe \{[^}]*Client-Win64-Shipping", text))
    progress = re.findall(r"info_set current daily progress (\d+)", text)
    points = re.findall(r"info_set total daily points (\d+)", text)

    ev = [
        f"阶段达到: {reached or '（无）'}",
        f"ok:quit app={quit_app}  杀游戏={killed}  TaskDisabled={disabled}",
    ]
    if progress:
        ev.append(f"current daily progress 末值={progress[-1]}")
    if points:
        ev.append(f"total daily points 末值={points[-1]}")

    # RUNNING：还没退出
    if not quit_app and still_running:
        return "RUNNING", ev + ["进程仍在运行且无终止标记"]

    # 到达完整收尾步骤
    if any(s in seq for s in FULL_FINAL):
        return "SUCCESS", ev + ["到达完整收尾步骤"]

    # 到达 claim mail 但未到 check*
    if "claim mail" in seq:
        if disabled:
            return "SUCCESS_PART", ev + ["到达 claim mail，但被 TaskDisabledException 中断"]
        return "SUCCESS_PART", ev + ["到达 claim mail，未见 check* 收尾"]

    if "claim daily" in seq:
        return "PARTIAL", ev + ["只到 claim daily"]

    if disabled:
        return "FAILED", ev + ["任务被禁用且未达 claim daily"]

    if quit_app:
        return "NO_TASK", ev + ["程序退出，但未执行任务"]

    return "UNKNOWN", ev + ["序列不完整且无终止标记"]


def latest_log():
    files = sorted(LOGDIR.glob("ok-script*.log"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def snapshot_marker():
    """记录基线：日志文件的集合与各自大小。

    ⚠️ ok-ww 退出时会**轮转日志**（`ok-script.log` -> `ok-script.YYYY-MM-DD.log`），
    故不能只盯一个文件 —— 必须记录目录快照，并在轮转后从新文件继续读。
    """
    files = {}
    for p in LOGDIR.glob("ok-script*.log"):
        try:
            files[p.name] = p.stat().st_size
        except OSError:
            pass
    return files


class LogWatcher:
    """跟踪 ok-ww 日志的**本次运行**内容（以文件偏移界定）。

    ⚠️ 早期版本用"读入全部既有日志 + 按 `ok:quit app` 分段取最后一段"，
    存在**假阳性**风险：若上一次运行被**外部强制终止**（无 `ok:quit app`），
    两次运行会被**合并成一段**，使本次运行借用上一次的成绩。
    实测在 ok-nte 上确实发生过。

    ⇒ 改为记录**基线偏移**，只读取运行开始后新增的部分。
    """

    def __init__(self):
        self._seen = {}
        self._buf = []
        self._baseline = snapshot_marker()
        for p in LOGDIR.glob("ok-script*.log"):
            try:
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
                if name not in self._baseline:
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
        return "\n".join(self._buf)


def read_new_since(path, offset):
    """（保留兼容）读取单文件自 offset 之后的内容。"""
    if path is None or not path.exists():
        return "", offset
    size = path.stat().st_size
    if size < offset:
        offset = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        data = f.read()
    return data, size


def main():
    print("=" * 76)
    print("ok-ww 终态判据")
    print("=" * 76)
    files = sorted(LOGDIR.glob("ok-script*.log"))
    print(f"\n{'文件':<28} {'判定':<14} 证据")
    print("-" * 76)
    for f in files:
        v, ev = verdict_from_log(read(f))
        print(f"{f.name:<28} {v:<14} {ev[0]}")

    p = latest_log()
    if p:
        v, ev = verdict_from_log(read(p))
        print(f"\n最近日志 {p.name}  =>  {v}")
        for e in ev:
            print(f"    {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
