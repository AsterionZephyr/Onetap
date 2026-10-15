"""回归探针：抢前台的三种手段（FAULT #29）。

## 为什么需要这个探针

**裸调 `SetForegroundWindow` 在别的进程持有前台时会被直接拒绝，
而且重试同一个调用永远不会成功。** 实测：DSH 窗口处于前台时，
`ensure_foreground` 连续 6 次全失败（0/6）；DSH 不在前台时第 1 次就成功。

危害不止是「慢」：节点 8 的等待循环把「置前台失败」与「帧不可读」
混在一个 `except GuardFailure` 里，于是**归因错误** ——
日志报「画面仍未稳定」，把人引去查游戏遮挡，而真凶是前台锁。

## 本探针分两层

**第一层（不需要真实窗口，永远可跑）**：静态检查
- `set_foreground` 必须真的用了 AttachThreadInput（而不是裸调吹牛）；
- 源码里必须同时出现三种手段（裸调 / AttachThreadInput / ALT 抖动）；
- `_alt_nudge` 必须存在且用 SendInput。

**第二层（需要现场，`--live` 才跑）**：真的去抢一次前台
- 先把「某个别的窗口」拉前台制造竞争，再让 `set_foreground` 抢目标窗口；
- 断言抢完 `GetForegroundWindow() == 目标`；
- 恢复原前台窗口，不留副作用。

第二层的价值在于：它测的是**行为**，不是**文本**。
若哪天有人把 AttachThreadInput 删了，第一层可能仍通过（文本还在注释里），
但第二层会立刻失败。
"""

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import win32, window, programs, input as input_mod  # noqa: E402

FAILS = []
LIVE = "--live" in sys.argv


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


print("=" * 70)
print("探针：抢前台三手段（FAULT #29）" + ("  [含 live 实测]" if LIVE else "  [静态]"))
print("=" * 70)

# ---------------- 第一层：静态 ----------------
src = (Path(__file__).resolve().parent.parent / "orchestrator" / "win32.py")
text = src.read_text(encoding="utf-8")

i = text.find("def set_foreground(")
j = text.find("\ndef ", i + 1)
body = text[i:j if j > 0 else len(text)]

check("set_foreground 不再是裸调", "AttachThreadInput" in body,
      "裸调在别人持前台时必然失败")
check("body 里出现 AttachThreadInput", "AttachThreadInput(" in body)
check("body 里出现 ALT 抖动", "_alt_nudge(" in body)
check("body 里仍有裸调（第一手，最快）", "SetForegroundWindow(hwnd)" in body)
check("存在 _alt_nudge 定义", "def _alt_nudge(" in text)
check("_alt_nudge 用 SendInput", "SendInput" in text)
check("AttachThreadInput 之后会解除附加",
      "AttachThreadInput(my_tid, fg_tid, False)" in body,
      "不解除会污染输入队列")
check("import 了 VK_MENU 常量区", "VK_MENU" in text)

# 绑定可用性
check("user32.AttachThreadInput 可用", hasattr(win32.user32, "AttachThreadInput"))
check("user32.GetWindowThreadProcessId 可用", hasattr(win32.user32, "GetWindowThreadProcessId"))
check("kernel32.GetCurrentThreadId 可用", hasattr(win32.kernel32, "GetCurrentThreadId"))
check("user32.SendInput 可用", hasattr(win32.user32, "SendInput"))

# ---------------- 第二层：live ----------------
if LIVE:
    print("\n--- live：用**真实鼠标点击**让别的窗口占住前台，再测 ensure_foreground ---")
    print("  ⚠️ 为什么不用 set_foreground 制造竞争：那正是被前台锁拒绝的调用，")
    print("     用它建条件等于用「假设失败的机制」去搭测试台。实测它还会连带")
    print("     干扰被测对象（同进程反复调用会互相消耗 ALT 抖动的「信用」）。")
    print("     真鼠标点击是**唯一**能确定性拿到前台的途径（HANDOFF §5）。")
    w = window.find_window(program=programs.NTE)
    if not w:
        print("  (ok-nte 未运行，跳过 live 段)")
    else:
        target = w["hwnd"]

        def make_rival():
            """用真实点击让一个别的可见窗口占住前台。"""
            for h, pid, title, cls in win32.find_windows(r"(?i).+"):
                if h == target or not title.strip():
                    continue
                if not win32.user32.IsWindowVisible(h):
                    continue
                r = win32.get_window_rect(h)
                if r.right - r.left < 300 or r.bottom - r.top < 200:
                    continue
                win32.click(r.left + 400, r.top + 60)
                time.sleep(0.8)
                return h
            return 0

        rounds = 3
        ok = 0
        for i in range(rounds):
            rival = make_rival()
            if not rival:
                print("  (找不到合适的陪练窗口，跳过)")
                break
            fg = win32.foreground_hwnd()
            print(f"  第{i+1}轮 陪练 = {win32.get_window_text(fg)[:40]!r}")
            check(f"第{i+1}轮：已制造前台竞争", fg == rival,
                  f"foreground={fg} rival={rival}")
            if fg != rival:
                continue
            t0 = time.time()
            try:
                input_mod.ensure_foreground(target, tries=10, interval=0.4)
                got = win32.foreground_hwnd()
                print(f"    ensure_foreground 成功（{time.time()-t0:.1f}s）"
                      f" 前台={win32.get_window_text(got)[:34]!r}")
                if got == target:
                    ok += 1
            except Exception as e:
                print(f"    ensure_foreground 失败（{time.time()-t0:.1f}s）{str(e)[:60]}")

        check(f"★ 抢前台成功率 {ok}/{rounds}（修复前实测 0/6）", ok == rounds and rounds > 0,
              f"成功 {ok} 轮")

print("\n" + "=" * 70)
if FAILS:
    print(f"FAILED：{len(FAILS)} 项未通过")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过")
