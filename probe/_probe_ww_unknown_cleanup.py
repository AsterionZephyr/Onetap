"""_probe_ww_unknown_cleanup.py — ok-ww UNKNOWN + 游戏残留 自动收尾回归

**为什么要这个探针**：用户裁定「遇到『每日任务已做完导致 ok-ww 失败且
进程/游戏不退出』时自行手动关闭，不询问用户」。这条修复先在 ok-nte 上
端到端验证过，**ok-ww 侧当时只做了单元验证**。本探针把它补上。

三层验证，全部基于**真实数据**：

  [1] 判据层：拿 ok-ww 历史上**真正没跑完**的会话（10-13 / 10-14 / 10-15），
      断言 verdict_for 必须报 unknown —— 不能报 success（INV-30）。
  [2] 分支层：静态检查 step9 的 UNKNOWN 分支同时看目标进程与游戏进程。
  [3] 端到端：**真起一个游戏**，跑 step9，断言游戏被清掉且退出码 0。
      端到端默认**跳过**（要起游戏、要几十秒），加 `--live` 才跑。

    python -X utf8 probe/_probe_ww_unknown_cleanup.py          # 静态 + 历史判据
    python -X utf8 probe/_probe_ww_unknown_cleanup.py --live   # 额外做端到端
"""

import inspect
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from orchestrator import programs, verdict, watchdog            # noqa: E402
from orchestrator.steps.common import step9_cleanup as S9       # noqa: E402

FAILED = []
LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs")


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


print("=" * 74)
print("ok-ww UNKNOWN + 游戏残留 自动收尾回归")
print("=" * 74)

# --- [1] 判据层：真实未完成会话必须报 unknown --------------------------------
print("\n[1] 判据层：真实「没跑完」的 ok-ww 会话必须报 unknown（不得报 success）")
# (日志文件, 会话起始时间戳) —— 均由 probe/_probe_ww_sessions.py 认定无完成标记
CASES = [
    ("ok-script.2026-10-15.log", "2026-10-15 20:54:59", "跑到体力不足 12 停下"),
    ("ok-script.2026-10-14.log", "2026-10-14 23:48:34", "中途停"),
    ("ok-script.2026-10-13.log", "2026-10-13 23:14:55", "中途 ok:quit app"),
]
for fname, ts, why in CASES:
    p = LOGDIR / fname
    if not p.exists():
        check(f"{fname} 存在（跳过）", False, "日志不在，无法验证")
        continue
    text = p.open(encoding="utf-8", errors="replace").read()
    i = text.find(ts)
    seg = text[i:] if i >= 0 else text
    v = verdict.verdict_for(program="ww", text=seg, still_running=False)
    got = v[0] if isinstance(v, tuple) else v
    check(f"{ts} → unknown", got == "unknown", f"实得 {got}（{why}）")

# 反向：真实完成的会话必须报 success（否则判据太宽松，等于没用）
print("\n  -- 反向对照：真实完成的会话必须报 success --")
for fname, ts in [("ok-script.log", "2026-10-16 23:52:24")]:
    p = LOGDIR / fname
    if not p.exists():
        continue
    text = p.open(encoding="utf-8", errors="replace").read()
    i = text.find(ts)
    seg = text[i:] if i >= 0 else text
    v = verdict.verdict_for(program="ww", text=seg, still_running=False)
    got = v[0] if isinstance(v, tuple) else v
    check(f"{ts} → success", got == "success", f"实得 {got}")

# --- [2] 分支层：静态检查 UNKNOWN 分支 ---------------------------------------
print("\n[2] 分支层：UNKNOWN 分支必须同时看目标进程与游戏进程")
SRC = inspect.getsource(S9)
m = re.search(r"if result == UNKNOWN and not args\.force:(.*?)\n    # --- ", SRC, re.S)
seg_src = m.group(1) if m else ""
check("找到 UNKNOWN 分支", bool(seg_src))
check("查了 watchdog.game_processes", "watchdog.game_processes(prog)" in seg_src)
check("查了 window.running", "window.running(prog)" in seg_src)
check("『均已不在』判据要求两者都空", "if not alive and not game:" in seg_src,
      "旧实现只判 not alive ⇒ 游戏还在也会说『无残留』")
check("有游戏残留时走 force_close", "watchdog.force_close(" in seg_src)
check("写明『自行收尾，不询问』", ("不询问" in seg_src or "自行收尾" in seg_src))
check("报『清掉 N/M 个』而非 killed_game 条数", "game_cleared" in SRC)

# --- [3] 端到端（默认跳过）---------------------------------------------------
if "--live" not in sys.argv:
    print("\n[3] 端到端：已跳过（加 --live 才跑；需真起游戏）")
else:
    print("\n[3] 端到端：真起游戏 → 跑 step9 → 断言清干净")
    game_exe = Path(r"D:\GAMES\Wuthering Waves\Wuthering Waves Game\Wuthering Waves.exe")
    if not game_exe.exists():
        check("游戏本体存在", False, str(game_exe))
    else:
        subprocess.Popen([str(game_exe)], cwd=str(game_exe.parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("      已拉起游戏，等 Client-Win64-Shipping.exe（最多 120s）…")
        for _ in range(24):
            time.sleep(5)
            if watchdog.game_processes(programs.get("ww")):
                break
        g0 = watchdog.game_processes(programs.get("ww"))
        check("游戏已起来", bool(g0), f"{[n for n,_,_ in g0]}")

        d = ROOT / "logs" / "runs" / "probe-ww-unknown-live"
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps({
            "run_dir": str(d), "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run": False, "program": "ww", "last_step": "8", "last_status": "ok",
            "skip_admin_check": False, "launched_by_us": True, "steps": {},
            "result": "unknown", "result_detail": "探针：模拟 ok-ww 异常退出后留下游戏",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        r = subprocess.run([sys.executable, "-X", "utf8", "-m",
                            "orchestrator.steps.common.step9_cleanup", "--run-dir", str(d)],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        check("step9 退出码 0", r.returncode == 0, f"实得 {r.returncode}")
        check("日志认出了游戏侧残留", "游戏侧仍有" in out)
        check("日志写明按裁定自行收尾", "不询问" in out)
        left = watchdog.game_processes(programs.get("ww"))
        check("游戏已被清干净", not left, f"仍剩 {[n for n,_,_ in left]}")

# --- 只读现场 -----------------------------------------------------------------
print("\n[现场] 只读")
for p in programs.ALL:
    t = [n for n, _, _ in watchdog.window.running(p)]
    g = [n for n, _, _ in watchdog.game_processes(p)]
    print(f"      {p.display:8s} 程序 {t}  游戏 {g}")

print("\n" + "=" * 74)
if FAILED:
    print(f"❌ {len(FAILED)} 项不符合预期：")
    for n in FAILED:
        print(f"   - {n}")
    sys.exit(1)
print("✅ 全部通过")
