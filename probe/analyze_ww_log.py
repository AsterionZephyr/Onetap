"""analyze_ww_log.py — 分析 ok-ww 任务日志，提取可靠的完成/失败信号

目标（Q1）：找到**不依赖进程消失**的完成判据。

分析维度：
  1. 任务生命周期的关键事件（开始/进度/结束）
  2. 成功完成的特征行
  3. 失败/异常的特征行
  4. 能否用「日志尾部模式」判定终态
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs")


def read(p):
    for enc in ("utf-8", "gbk", "utf-8-sig"):
        try:
            return p.read_text(encoding=enc, errors="replace")
        except Exception:
            continue
    return ""


def main():
    files = sorted(LOGDIR.glob("ok-script*.log"))
    print(f"找到 {len(files)} 个日志文件：")
    for f in files:
        print(f"  {f.name}  {f.stat().st_size:,} bytes")

    # 关键词统计（跨所有日志）
    PATTERNS = {
        "任务切换": r"DailyTask:info_set current task (.+)",
        "进度": r"info_set current daily progress (\d+)",
        "总点数": r"info_set total daily points (\d+)",
        "任务完成_中文": r"每日任务已完成|任务已完成|已完成",
        "成功执行": r"成功执行任务",
        "退出游戏": r"正在退出游戏",
        "被禁用": r"is disabled, raise Exception",
        "TaskDisabledException": r"TaskDisabledException",
        "异常_Exception": r"Exception|Traceback|Error",
        "拒绝访问": r"拒绝访问|Access is denied|WinError 5",
        "quit app": r"ok:quit app",
        "窗口关闭": r"MainWindow:Window closed",
        "handler stopping": r"handler:handler stopping",
        "鼠标回位": r"MouseResetTask:move mouse back",
        "AutoStart": r"auto.?start|AutoStart",
    }

    print("\n" + "=" * 70)
    print("跨日志关键词统计")
    print("=" * 70)
    agg = Counter()
    for f in files:
        txt = read(f)
        for name, pat in PATTERNS.items():
            agg[name] += len(re.findall(pat, txt, re.I))
    for name in PATTERNS:
        print(f"  {name:24s} {agg[name]:6d}")

    # 逐个文件看尾部模式
    print("\n" + "=" * 70)
    print("各日志的尾部 12 行（找终态特征）")
    print("=" * 70)
    for f in files:
        txt = read(f)
        lines = [l for l in txt.splitlines() if l.strip()]
        print(f"\n--- {f.name} （{len(lines)} 行）---")
        for l in lines[-12:]:
            print(f"    {l[:150]}")

    # 专门找「任务生命周期」序列
    print("\n" + "=" * 70)
    print("任务阶段序列（current task 变化，取最近一次运行）")
    print("=" * 70)
    latest = max(files, key=lambda p: p.stat().st_mtime)
    txt = read(latest)
    seq = re.findall(r"(\d\d:\d\d:\d\d),\d+ INFO TaskExecutor DailyTask:info_set current task (.+)", txt)
    if seq:
        print(f"文件：{latest.name}")
        prev = None
        for t, task in seq:
            if task != prev:
                print(f"  {t}  -> {task}")
                prev = task
    else:
        print("  未匹配到阶段序列（格式可能不同）")
        # 退而求其次：直接抓含 current task 的行
        for l in txt.splitlines():
            if "current task" in l:
                print(f"    {l[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
