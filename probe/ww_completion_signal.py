"""ww_completion_signal.py — 确定 ok-ww 的可靠完成判据（Q1 核心）

从日志对比「成功完成」与「非成功结束」的差异。

关键候选信号：
  A. TaskExecutor process:Killing process(es) ... Client-Win64-Shipping.exe
     -> 任务主动杀游戏 = 任务结束的标志动作
  B. MainWindow:Window closed exit_event.is_set
     -> exit_event 已设置 = 程序自己决定退出（而非用户关窗）
  C. ok:quit app  -> 终止标记

需要验证：B 的 "is_set" vs "is not set" 是否区分成功/失败。
"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs")


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def main():
    files = sorted(LOGDIR.glob("ok-script*.log"))
    print("=" * 78)
    print("各次运行的终态特征对比")
    print("=" * 78)

    rows = []
    for f in files:
        txt = read(f)
        lines = txt.splitlines()

        # A. 是否杀了游戏进程（任务收尾动作）
        killed_game = bool(re.search(
            r"Killing process\(es\).*Client-Win64-Shipping|"
            r"Trying to kill the exe.*Client-Win64-Shipping", txt))
        kill_lines = re.findall(r"Trying to kill the exe \{'pid': (\d+)", txt)

        # B. exit_event 状态
        m = re.search(r"MainWindow:Window closed exit_event\.(is_set|is not set)", txt)
        exit_ev = m.group(1) if m else "(无)"

        # C. 终止标记
        quit_app = "ok:quit app" in txt

        # D. 任务阶段里有没有走完关键步骤
        tasks = re.findall(r"DailyTask:info_set current task (.+)", txt)
        uniq = []
        for t in tasks:
            if not uniq or uniq[-1] != t:
                uniq.append(t)

        # E. 错误计数
        n_err = len(re.findall(r"\bERROR\b", txt))
        n_taskerr = len(re.findall(r"TaskDisabledException", txt))

        # F. 最后一条非空行
        last = next((l for l in reversed(lines) if l.strip()), "")

        rows.append({
            "file": f.name, "lines": len(lines),
            "killed_game": killed_game, "kill_pids": kill_lines,
            "exit_event": exit_ev, "quit_app": quit_app,
            "tasks": uniq, "n_err": n_err, "n_taskerr": n_taskerr,
            "last": last[:90],
        })

    print(f"\n{'文件':<28} {'行':>5} {'杀游戏':>6} {'exit_event':>14} {'quit':>5} {'ERR':>4} {'含每日任务':>8}")
    print("-" * 78)
    for r in rows:
        has_daily = any("claim" in t or "task" in t and "esc" not in t for t in r["tasks"])
        print(f"{r['file']:<28} {r['lines']:>5} "
              f"{'是' if r['killed_game'] else '否':>6} "
              f"{r['exit_event']:>14} {'是' if r['quit_app'] else '否':>5} "
              f"{r['n_err']:>4} {'是' if has_daily else '否':>8}")

    print("\n" + "=" * 78)
    print("详细：含「杀游戏进程」的运行（= 任务真正跑到了收尾）")
    print("=" * 78)
    for r in rows:
        if r["killed_game"]:
            print(f"\n--- {r['file']} ---")
            print(f"  被杀的游戏 PID: {r['kill_pids']}")
            print(f"  exit_event: {r['exit_event']}")
            print(f"  任务阶段序列: {r['tasks']}")
            print(f"  末行: {r['last']}")

    print("\n" + "=" * 78)
    print("判定")
    print("=" * 78)
    print("""
候选判据（按可靠性排序）：

1. 【最强】日志中出现：
       TaskExecutor process:Killing process(es) ... Client-Win64-Shipping.exe
   => ok-ww 完成任务后**主动关闭游戏**，这是任务收尾的标志动作。

2. 【强】MainWindow:Window closed exit_event.is_set
   => exit_event **已被设置** = 程序自己决定退出（任务驱动），
      而非用户手动关窗（is not set）。

3. 【终止标记】MainThread ok:quit app   （总是最后一行）

4. 【反例特征】TaskDisabledException / is disabled, raise Exception
   => 任务被禁用或异常中止
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
