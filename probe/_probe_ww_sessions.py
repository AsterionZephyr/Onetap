"""_probe_ww_sessions.py — 把 ok-ww 日志按「会话」切开，列出每轮结局

用途：找「已做完而异常退出」的真实样本，供 UNKNOWN 自动收尾路径做回归对照。

会话边界 = `ok:ok-script init` 那一行。**不能按 `ok:quit app` 切** ——
异常退出的会话根本不写这行（这正是 LogWindow 按字节偏移切窗口的原因）。

    python -X utf8 probe/_probe_ww_sessions.py [日志路径]
"""

import sys
from pathlib import Path

DEFAULT = Path(r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs\ok-script.log")

path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if not path.exists():
    sys.exit(f"找不到日志：{path}")

lines = path.open(encoding="utf-8", errors="replace").readlines()

DONE = ("Daily Task Completed", "Successfully Executed")
QUIT = "ok:quit app"
INIT = "ok:ok-script init"
BAD = ("Exception", "ERROR", "Traceback")

sessions, cur = [], None
for ln in lines:
    if INIT in ln:
        if cur:
            sessions.append(cur)
        cur = {"start": ln[:19], "n": 0, "done": False, "quit": False,
               "bad": [], "tasks": 0, "killed": 0}
    if cur is None:
        continue
    cur["n"] += 1
    if any(k in ln for k in DONE):
        cur["done"] = True
    if QUIT in ln:
        cur["quit"] = True
    if "开始任务" in ln or "TaskExecutor:开始" in ln:
        cur["tasks"] += 1    if "Trying to kill the exe" in ln:
        cur["killed"] += 1
    if any(k in ln for k in BAD):
        cur["bad"].append(ln.strip()[:120])
if cur:
    sessions.append(cur)

print(f"日志：{path}")
print(f"共 {len(sessions)} 次会话\n")
abnormal = []
for i, s in enumerate(sessions, 1):
    tag = "完成" if s["done"] else ("**无完成标记**")
    quit_s = "quit" if s["quit"] else "**未写 quit**"
    print(f"[{i:2d}] {s['start']}  {tag:14s} {quit_s:12s} "
          f"行={s['n']:6d} 任务痕={s['tasks']:3d} 杀游戏={s['killed']}")
    for b in s["bad"][:2]:
        print(f"        ! {b}")
    if not s["done"]:
        abnormal.append((i, s))

print(f"\n=== 无完成标记的会话（「已做完而异常退出」的候选样本）：{len(abnormal)} 个 ===")
for i, s in abnormal:
    print(f"  [{i}] {s['start']}  行={s['n']}  quit={s['quit']}  任务痕={s['tasks']}")
