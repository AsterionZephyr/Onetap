"""_probe_unknown_cleanup.py — UNKNOWN 分支的自动收尾回归探针

**为什么要这个探针**：用户明确裁定了一件事 ——

> 遇到「每日任务已做完导致 ok-ww 失败且进程/游戏不退出」时
> **自行手动关闭，不询问用户**。

而旧实现接不住这个要求，有两处漏洞：

1. `step9_cleanup.py` 的 UNKNOWN 分支只看 `window.running(prog)`
   （**目标程序自己**的进程）。可是用户说的这个情形里，ok-ww 进程
   **恰恰是已经退出的那一个** —— 留下的是**游戏**。于是旧代码打印
   「ok-ww 进程已不在 —— 无残留，无需清理」**而游戏仍在跑**。
   这与 FAULT #31/#32 同型：报了个让人以为一切干净的结论。

2. 就算落到常规清理路径也没用：`cleanup.run_cleanup` 按
   `process_prefix` 只杀**目标程序目录下**的进程，而游戏
   （`Client-Win64-Shipping.exe` / `HTGame.exe` / `NTEGame.exe`）
   根本不在那个目录里 ⇒ 报告清理完成而游戏照跑。

另有一个实测踩到的 AttributeError：`args.keep_game` 是**主控 main.py**
的参数，节点子进程默认收不到，必须在 step9 的 `extra_args` 里自己声明。

本探针**不杀任何进程**（纯静态 + 只读），随时可跑：

    python -X utf8 probe/_probe_unknown_cleanup.py
"""

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from orchestrator import programs, watchdog                    # noqa: E402
from orchestrator.steps.common import step9_cleanup as S9      # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


SRC = inspect.getsource(S9)

print("=" * 74)
print("UNKNOWN 分支自动收尾回归探针")
print("=" * 74)

# --- 1. UNKNOWN 分支必须查游戏侧 ---------------------------------------------
print("\n[1] UNKNOWN 分支必须同时看目标进程与游戏进程")
# 取 UNKNOWN 分支那一段
m = re.search(r'if result == UNKNOWN and not args\.force:(.*?)\n    # --- ',
              SRC, re.S)
seg = m.group(1) if m else ""
check("找到 UNKNOWN 分支", bool(seg))
check("分支内查了 watchdog.game_processes", "watchdog.game_processes(prog)" in seg)
check("分支内查了 window.running", "window.running(prog)" in seg)
check("『均已不在』判据同时要求两者为空",
      "if not alive and not game:" in seg,
      "旧实现只判 not alive ⇒ 游戏还在也会说『无残留』")
check("有游戏残留时走 force_close（不是只靠 run_cleanup）",
      "watchdog.force_close(" in seg)
check("显式写明『自行收尾，不询问』",
      "不询问" in seg or "自行收尾" in seg)

# --- 2. run_cleanup 够不着游戏：把这条证据固化 --------------------------------
print("\n[2] 为什么不能只靠 run_cleanup（证据固化）")
from orchestrator import cleanup as C                            # noqa: E402
csrc = inspect.getsource(C)
check("run_cleanup 按 process_prefix 过滤",
      "process_prefix" in C.plan_cleanup.__doc__ or "_resolve(" in csrc)
for key, gname in (("ww", "Client-Win64-Shipping.exe"),
                   ("nte", "HTGame.exe")):
    p = programs.get(key)
    check(f"{gname} 不在 {key} 的 process_prefix 下（故清理够不着）",
          not (p.process_prefix or "").lower().count(gname.lower()),
          f"process_prefix={p.process_prefix!r}")
check("游戏名不在目标程序可杀名单里（ww）",
      "Client-Win64-Shipping.exe".lower()
      not in {n.lower() for n in (programs.get("ww").process_names or [])})
check("force_close 才显式处理游戏",
      "close_game" in inspect.signature(watchdog.force_close).parameters)

# --- 3. keep_game 必须自己声明（实测 AttributeError）-------------------------
print("\n[3] --keep-game 必须在 step9 自己声明")
class _AP:
    def __init__(self):
        self.opts = {}

    def add_argument(self, *a, **k):
        for x in a:
            if x.startswith("--"):
                self.opts[x] = k


ap = _AP()
S9.extra_args(ap)
check("extra_args 声明了 --keep-game", "--keep-game" in ap.opts,
      f"实际声明 {sorted(ap.opts)}")
check("--keep-game 是 store_true",
      ap.opts.get("--keep-game", {}).get("action") == "store_true")

# 端到端：真跑一次 argparse，确认 args.keep_game 可访问
import argparse                                                  # noqa: E402
real = argparse.ArgumentParser()
S9.extra_args(real)
ns = real.parse_args([])
check("不加参数时 args.keep_game 存在且为 False",
      hasattr(ns, "keep_game") and ns.keep_game is False,
      "旧实现直接 args.keep_game ⇒ AttributeError")
ns2 = real.parse_args(["--keep-game"])
check("带 --keep-game 时为 True", ns2.keep_game is True)

# --- 4. 措辞不得用 killed_game 条数冒充「清掉了几个」-------------------------
print("\n[4] 措辞：报『清掉的数量』而非 killed_game 的条数")
check("有 game_cleared 字段（如实反映清掉几个）",
      "game_cleared" in SRC,
      "launcher 常是收到 WM_CLOSE 后自行退出 ⇒ killed_game 为空但确实清掉了")
check("不再写『终止游戏 {len(...killed_game)} 个』",
      "终止游戏 {len(wr.get('killed_game'" not in SRC)

# --- 5. 只读现场 ---------------------------------------------------------------
print("\n[5] 只读现场")
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
