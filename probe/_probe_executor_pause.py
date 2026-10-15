"""探针：诊断 ok-nte 是否处于「执行器暂停」状态（FAULT #30）。

## 背景

ok-nte 的日志里有这样一条**只出现一次、之后就永久沉默**的记录：

```
ERROR update_window_size hwnd_window:og.executor.pause pos_invalid: (-32000, -32000, 0, 0)
```

`-32000` 正是本仓库早就记为 `win32.ICONIC_SENTINEL` 的**最小化哨兵值**。
ok-nte 检测到游戏窗口被最小化（坐标为哨兵值），就把自己的**执行器暂停**，
并且**不会自行恢复** —— 实测恢复窗口后它只写了两行 `hwnd changed,connected:1`，
然后再度沉默（静默 3.3 分钟后仍是死寂）。

## 危害

框架的等待循环只看「日志里有没有终止标记」+「进程还在不在」。
执行器永久暂停时：进程**还在**、终止标记**永远不来** ⇒
框架必然一路轮询到 `--total-timeout`（默认 1800s）才报 TIMEOUT，
**白烧半小时**且不会报「卡住了」。

## 本探针做什么（只读，不改状态）

1. 在 ok-nte 日志里找 `og.executor.pause pos_invalid` 与随后的 `hwnd changed,connected:1`；
2. 判断「最后一次 pause 之后是否还有实质业务日志」——
   若 pause 之后只剩窗口尺寸类日志、没有任何 `Task*:` 业务行，
   即判定为「执行器已永久暂停」；
3. 报告游戏窗口当前是否仍是最小化。

`--live` 时额外检查当前进程与窗口状态。
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import verdict as verdict_mod  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


PAUSE_RE = re.compile(r"og\.executor\.pause\s+pos_invalid:\s*\((-?\d+),\s*(-?\d+)")
RECONNECT_RE = re.compile(r"hwnd changed,connected:1")

ICONIC_SENTINEL = -32000

# 业务行：任务执行器真正在做事的证据。
# ⚠️ 必须覆盖**所有**任务类，不能只写 Daily* —— 实测 10-12 那次卡顿
# 期间跑的是 FishingTask（钓鱼，789 轮），只用 Daily 会把它误判成「没干活」。
BIZ_RE = re.compile(r"TaskExecutor\s+\w+Task[:：]"
                    r"|开始任务|任务完成|found Labels|info_set (轮次|当前阶段)")

# 非业务行：窗口尺寸/连接状态之类的背景噪声
NOISE_RE = re.compile(r"(update_window_size|hwnd_window|connected:|do_update_window_size)")

# 退出/收尾标记：出现这些说明进程在正常收场，不是卡死
EXIT_RE = re.compile(r"(og\.executor\.pause|ok:quit app|Executor destroy|"
                     r"Attempting to terminate process|handler stopping)")


def analyze(text):
    """返回 dict：pause 次数、最后一次 pause 的位置、之后是否还有业务日志。

    ⚠️ 判定「卡死」**不能只看「pause 之后有没有业务行」**。
    实测 `ok-script.2026-10-12.log`：20:07:19 出现哨兵 pause，
    但 20:07:40 又跑了 FishingTask、20:11:22 正常 `ok:quit app` 收尾 ——
    **它是活过来的**。那条 pause 期间窗口被人手动最小化过，
    窗口恢复后 ok-nte 自己继续干活。

    所以「卡死」的判据要更严：pause 之后**既没有业务行、也没有任何收尾动作**，
    才是「停在那里不动了」。
    """
    pauses = list(PAUSE_RE.finditer(text))
    info = {
        "pause_count": len(pauses),
        "sentinel_hits": 0,
        "last_pause_at": None,
        "biz_after_last_pause": 0,
        "reconnect_after_last_pause": 0,
        "exit_after_last_pause": 0,
        "stalled": False,
    }
    for m in pauses:
        if int(m.group(1)) <= ICONIC_SENTINEL and int(m.group(2)) <= ICONIC_SENTINEL:
            info["sentinel_hits"] += 1
    if not pauses:
        return info

    last = pauses[-1]
    info["last_pause_at"] = last.start()
    tail = text[last.end():]
    for line in tail.splitlines():
        if not line.strip():
            continue
        if BIZ_RE.search(line) and not NOISE_RE.search(line):
            info["biz_after_last_pause"] += 1
        if RECONNECT_RE.search(line):
            info["reconnect_after_last_pause"] += 1
        if EXIT_RE.search(line):
            info["exit_after_last_pause"] += 1

    # 卡死 = 出现过哨兵 pause，且之后**既没干活、也没收尾**
    info["stalled"] = (info["sentinel_hits"] > 0
                       and info["biz_after_last_pause"] == 0
                       and info["exit_after_last_pause"] == 0)
    return info


print("=" * 70)
print("探针：ok-nte 执行器暂停诊断（FAULT #30）")
print("=" * 70)

# ---- 1. 纯文本用例：合成「暂停后再无业务行」 ----
print("\n--- 合成用例（不依赖现场）---")
stalled_text = "\n".join([
    "2026-10-16 03:34:44,434 INFO TaskExecutor DailyClaimTask:开启活跃度面板",
    "2026-10-16 03:34:45,482 INFO TaskExecutor DailyClaimTask:send f1 key to open the panel",
    "2026-10-16 03:34:46,400 ERROR update_window_size hwnd_window:og.executor.pause "
    "pos_invalid: (-32000, -32000, 0, 0) ",
    "2026-10-16 03:43:28,132 INFO update_window_size hwnd_window:hwnd changed,connected:1",
    "2026-10-16 03:43:28,137 INFO update_window_size hwnd_window:do_update_window_size "
    "changed,visible:True,exists:1",
])
a = analyze(stalled_text)
print(f"  pause={a['pause_count']} 哨兵={a['sentinel_hits']} "
      f"暂停后业务行={a['biz_after_last_pause']} 重连={a['reconnect_after_last_pause']}")
check("✓ 识别出「暂停且永不复原」", a["stalled"] is True)
check("✓ 哨兵坐标被认成最小化", a["sentinel_hits"] == 1)

# ---- 2. 恢复了的用例：暂停后仍有业务行 ⇒ 不算卡死 ----
recovered_text = stalled_text + "\n" + "\n".join([
    "2026-10-16 03:50:00,000 INFO TaskExecutor DailyRoutineTask:任务完成: 日常领取",
    "2026-10-16 03:50:05,000 INFO TaskExecutor BaseNTETask:found Labels.f1_panel "
    "Box(name='Labels.f1_panel', x=33, y=36, width=51, height=50, confidence=99)",
])
b = analyze(recovered_text)
print(f"  pause={b['pause_count']} 暂停后业务行={b['biz_after_last_pause']}")
check("✓ 暂停后又干活了 ⇒ 不误报卡死", b["stalled"] is False,
      "瞬时的 pos_invalid 会自行恢复（实测 L478 那类）")

# ---- 3. 没有暂停的日志 ----
clean_text = "2026-10-16 03:34:44,434 INFO TaskExecutor DailyClaimTask:开启活跃度面板"
c = analyze(clean_text)
print(f"  pause={c['pause_count']}")
check("✓ 无暂停记录 ⇒ 不报卡死", c["stalled"] is False and c["pause_count"] == 0)

# ---- 4. 只在日志**尾部**判定的边界：pause 在很早就出现但后面一直有业务 ----
long_ok = "\n".join(
    ["2026-01-01 00:00:00,000 ERROR update_window_size hwnd_window:og.executor.pause "
     "pos_invalid: (-32000, -32000, 0, 0)"]
    + [f"2026-01-01 00:0{i}:00,000 INFO TaskExecutor DailyRoutineTask:任务完成: 任务{i}"
       for i in range(5)]
)
d = analyze(long_ok)
check("✓ 早期有 pause 但后续持续干活 ⇒ 不报卡死", d["stalled"] is False,
      f"暂停后业务行={d['biz_after_last_pause']}")

# ---- 5. 真实日志回归 ----
print("\n--- 真实日志 ---")
ld = Path(verdict_mod.NTE_LOGDIR)
logs = sorted(ld.glob("ok-script*.log")) if ld.exists() else []
if not logs:
    print(f"  (日志目录不存在或为空：{ld})")
else:
    recovered_real = 0
    for f in logs:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  {f.name}: 读不了（{e}）")
            continue
        info = analyze(text)
        tag = "⛔ 已卡死" if info["stalled"] else "正常"
        print(f"  {f.name:34} pause={info['pause_count']} "
              f"哨兵={info['sentinel_hits']} 暂停后业务={info['biz_after_last_pause']:3d} "
              f"收尾={info['exit_after_last_pause']:2d}  {tag}")
        # ★ 关键回归：10-12 那次 pause 后**活过来了**（跑了 FishingTask 并正常退出）
        #   绝不能报「卡死」。这就是本探针最初版本的漏洞。
        if f.name == "ok-script.2026-10-12.log":
            check("★ 10-12 那次 pause 后自行恢复 ⇒ 不得报卡死",
                  info["stalled"] is False,
                  f"暂停后业务={info['biz_after_last_pause']} 收尾={info['exit_after_last_pause']}")
            check("★ 10-12 那次确实检出过哨兵 pause（夹具有效）",
                  info["sentinel_hits"] == 1)
            recovered_real += 1
    if recovered_real == 0:
        print("  (注：10-12 日志不在，跳过该回归用例)")

# ---- 6. live：当前窗口状态 ----
if "--live" in sys.argv:
    print("\n--- live：当前窗口状态 ---")
    from orchestrator import win32, watchdog, programs
    for h, pid, title, cls in watchdog.game_windows(programs.NTE):
        if cls != "UnrealWindow":
            continue
        r = win32.get_window_rect(h)
        ic = bool(win32.user32.IsIconic(h))
        print(f"  游戏主窗口 hwnd={h} rect=({r.left},{r.top}) 最小化={ic}")
        check("✓ 游戏窗口未处于最小化哨兵位置",
              not (r.left <= ICONIC_SENTINEL and r.top <= ICONIC_SENTINEL),
              f"rect=({r.left},{r.top})")

print("\n" + "=" * 70)
if FAILS:
    print(f"FAILED：{len(FAILS)} 项未通过")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过")
