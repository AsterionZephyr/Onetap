"""_probe_force_close_all.py — 跨程序清理的回归探针（FAULT #32）

**为什么要这个探针**：`force_close(program=None)` 的 `None` **不等于「全部」**，
而是回落到 `programs.DEFAULT`（ok-ww）。于是它只按 ok-ww 的 `game_names`
（`Client-Win64-Shipping.exe`）去查游戏进程，查不到就打印
「游戏进程已全部退出」—— **这句话为真，却是误导**：
ok-nte 的游戏（`HTGame.exe` / `NTEGame.exe`）一个都没碰。

2026-10-16 实测：`--target both` 跑完，ok-nte 的 launcher `NTEGame.exe`
残留（pid=25736，7 个窗口）。调 `force_close(None)` 后它**报告已全部退出**，
但那进程仍在。改调 `force_close(None, all_programs=True)` 才真的清掉。

这与 FAULT #31 同型：**报了个让人以为一切干净的结论**。

本探针**不杀任何进程**（纯静态 + 只读判定），随时可跑：

    python -X utf8 probe/_probe_force_close_all.py
"""

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from orchestrator import programs, watchdog          # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


print("=" * 74)
print("跨程序清理回归探针（FAULT #32）")
print("=" * 74)

# --- 1. 静态：force_close 必须支持 all_programs -------------------------------
print("\n[1] 静态：force_close 的签名与分派")
sig = inspect.signature(watchdog.force_close)
check("force_close 有 all_programs 参数", "all_programs" in sig.parameters,
      f"实际参数 {list(sig.parameters)}")
check("all_programs 默认 False",
      sig.parameters["all_programs"].default is False,
      f"实际 {sig.parameters['all_programs'].default!r}")
check("存在 _force_close_all", hasattr(watchdog, "_force_close_all"))

src = inspect.getsource(watchdog.force_close)
check("force_close 里 all_programs 会分派到 _force_close_all",
      "if all_programs:" in src and "_force_close_all(" in src)

# --- 2. 语义：None 回落到 DEFAULT，不是「全部」--------------------------------
print("\n[2] 语义：program=None 落到哪个程序")
d = programs.get(None)
check("programs.get(None) 回落到 DEFAULT", d.key == programs.DEFAULT.key,
      f"get(None)={d.key!r}  DEFAULT={programs.DEFAULT.key!r}")
check("DEFAULT 不是通配", programs.DEFAULT.key in [p.key for p in programs.ALL],
      f"DEFAULT={programs.DEFAULT.key!r}")

# --- 3. 关键证据：两程序的 game_names 不同 → 单程序清理必然漏 ------------------
print("\n[3] 关键证据：game_names 不重叠，故单程序清理必然漏")
ww = programs.get("ww")
nte = programs.get("nte")
print(f"      ww.game_names  = {ww.game_names}")
print(f"      nte.game_names = {nte.game_names}")
nteg = "NTEGame.exe"
check(f"{nteg} 不在 ww.game_names 里（故 force_close(None) 看不见它）",
      nteg.lower() not in {n.lower() for n in (ww.game_names or [])})
check(f"{nteg} 在 nte.game_names 里（故需 all_programs 才能清）",
      nteg.lower() in {n.lower() for n in (nte.game_names or [])})
check("两程序 game_names 至少有一个不重叠元素",
      bool({n.lower() for n in (ww.game_names or [])}
           ^ {n.lower() for n in (nte.game_names or [])}),
      "若完全重叠，则单程序清理也能覆盖，本修复就没必要")

# --- 4. _force_close_all 遍历 ALL 且给复检结果 --------------------------------
print("\n[4] _force_close_all 的行为约定")
allsrc = inspect.getsource(watchdog._force_close_all)
check("遍历 programs.ALL", "programs_mod.ALL" in allsrc)
check("对每个程序调 force_close", "force_close(p," in allsrc)
check("返回里含 per_program", "per_program" in allsrc)
check("返回里含 leftover（残留复检）", "leftover" in allsrc)
check("dry_run 时不复检（不碰进程）", "if not dry_run:" in allsrc)

# --- 5. --target both 的汇总段必须有跨程序复检 --------------------------------
print("\n[5] --target both 的汇总段会做跨程序复检")
main_py = ROOT / "orchestrator" / "steps" / "main.py"
msrc = main_py.read_text(encoding="utf-8")
check("run_both 里有『串联复检』", "串联复检" in msrc)
check("复检同时查两个程序", "for key, disp, _rc, _dt in overall:" in msrc)
check("复检会列出游戏侧残留", "watchdog.game_processes(prog)" in msrc)
check("main.py 导入了 window", "from .. import window" in msrc)

# --- 6. 只读现场（不杀任何东西）------------------------------------------------
print("\n[6] 只读现场：现在到底剩什么")
for p in programs.ALL:
    t = [n for n, _, _ in watchdog.window.running(p)]
    g = [n for n, _, _ in watchdog.game_processes(p)]
    print(f"      {p.display:8s} 程序 {t}  游戏 {g}")
print("      （本探针只读，不终止任何进程）")

print("\n" + "=" * 74)
if FAILED:
    print(f"❌ {len(FAILED)} 项不符合预期：")
    for n in FAILED:
        print(f"   - {n}")
    sys.exit(1)
print("✅ 全部通过")
