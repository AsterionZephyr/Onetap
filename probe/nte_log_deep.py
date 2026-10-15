"""nte_log_deep.py — 深挖 ok-nte 的任务终止标记（用含真实运行的日志）

最新日志只有初始化；改用体积大、时间完整的日志（如 10-02 425KB）。
找：
  1. 任务开始/结束的成对标记
  2. 「完成」类中文提示
  3. 任务类切换（TaskExecutor <Name>Task）
  4. 终态（quit app 前最后几行）
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
    # 选最大的日志（最可能含完整任务）
    files = sorted(LOGDIR.glob("ok-script*.log"))
    big = max(files, key=lambda p: p.stat().st_size)
    print(f"分析目标：{big.name}  {big.stat().st_size:,} bytes")
    t = read(big)

    print("\n" + "=" * 76)
    print("[1] 任务类（TaskExecutor <Name>Task）出现次数")
    print("=" * 76)
    c = Counter(re.findall(r"TaskExecutor (\w+)", t))
    for name, n in c.most_common(25):
        print(f"  {name:32s} {n:6d}")

    print("\n" + "=" * 76)
    print("[2] 含「完成」的行（去重后前 20 条）")
    print("=" * 76)
    seen = set()
    for l in t.splitlines():
        if "完成" in l:
            key = re.sub(r"^\S+ \S+ ", "", l)[:90]
            if key not in seen:
                seen.add(key)
                print(f"  {l.strip()[:150]}")
            if len(seen) >= 20:
                break

    print("\n" + "=" * 76)
    print("[3] 含「成功」/「失败」的行（去重前 15 条）")
    print("=" * 76)
    seen2 = set()
    for l in t.splitlines():
        if ("成功" in l or "失败" in l) and "INFO" in l:
            key = re.sub(r"^\S+ \S+ ", "", l)[:80]
            if key not in seen2:
                seen2.add(key)
                print(f"  {l.strip()[:150]}")
            if len(seen2) >= 15:
                break

    print("\n" + "=" * 76)
    print("[4] start task / 任务调度")
    print("=" * 76)
    for l in t.splitlines():
        if re.search(r"start task|stop task|task list|执行任务|任务列表", l):
            print(f"  {l.strip()[:150]}")

    print("\n" + "=" * 76)
    print("[5] 尾部 25 行（终态）")
    print("=" * 76)
    lines = [l for l in t.splitlines() if l.strip()]
    for l in lines[-25:]:
        print(f"  {l[:160]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
