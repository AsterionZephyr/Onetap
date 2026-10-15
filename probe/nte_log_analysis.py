"""nte_log_analysis.py — 分析 ok-nte 任务日志，找终态判据（Q2 前置）

关键问题：ok-nte 与 ok-ww 的任务阶段名是否相同？
  ok-ww  : claim daily / claim mail / check weekly garden / check discarded echo
  ok-nte : ？（待查，任务集不同：异界领域 / 一咖舍 / 日常领取 / 喷泉签到 ...）
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-nte\data\apps\ok-nte\working\logs")


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def main():
    files = sorted(LOGDIR.glob("ok-script*.log"))
    print(f"ok-nte 日志 {len(files)} 个")
    for f in files:
        print(f"  {f.name:<28} {f.stat().st_size:>10,} bytes")

    # 找阶段标记的模式
    print("\n" + "=" * 74)
    print("探测阶段标记的写法")
    print("=" * 74)
    pats = {
        "info_set current task": r"info_set current task (.+)",
        "TaskExecutor 类名": r"TaskExecutor (\w+):",
        "任务开始/结束": r"(start task|finish task|task done|TaskFinished|TaskStarted)",
        "完成/成功": r"(完成|成功|Finished|Success|Done)",
        "失败/错误": r"(失败|错误|Failed|Error|Exception)",
        "中文任务名": r"[\u4e00-\u9fff]{2,}\s*(?:任务|完成|开始)",
    }
    agg = Counter()
    samples = {}
    for f in files:
        t = read(f)
        for name, p in pats.items():
            ms = re.findall(p, t)
            agg[name] += len(ms)
            if ms and name not in samples:
                samples[name] = ms[:6]
    for name in pats:
        print(f"  {name:26s} {agg[name]:6d}   样例: {samples.get(name, [])}")

    # 最新的那个文件：看尾部
    latest = max(files, key=lambda p: p.stat().st_mtime)
    print(f"\n{'='*74}")
    print(f"最新日志 {latest.name} 尾部 30 行")
    print("=" * 74)
    lines = [l for l in read(latest).splitlines() if l.strip()]
    for l in lines[-30:]:
        print("  " + l[:160])

    # 提取 current task 序列
    print(f"\n{'='*74}")
    print("current task 序列（最新文件）")
    print("=" * 74)
    seq = re.findall(r"info_set current task (.+)", read(latest))
    uniq = []
    for s in seq:
        s = s.strip()
        if not uniq or uniq[-1] != s:
            uniq.append(s)
    for s in uniq:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
