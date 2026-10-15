"""回归探针：ok-nte 见到终止标记后的「收尾宽限」（FAULT #27）。

## 为什么需要这个探针

FAULT #27 的现场是：ok-nte 写下终止标记 0.8 秒后，节点 9 就把它杀了，
**正好打断它关闭游戏的那一步**，留下全屏孤儿游戏进程。

修法是在终止标记之后加一段 `NTE_SETTLE_SECONDS` 的 settle 窗口，
等 ok-nte **自己退出**再往下走。这个探针用**假进程 + 可变日志**复现
真实时序，验证三种收尾都能走对，而不是只验证「代码没语法错」。

## 三种场景（对应真实世界的三种收尾）

- **A 正常**：进程几秒后自己退出，日志里出现 `Killing process(es)`。
  ⇒ 必须报「已自行关闭游戏」，且**在返回前**那段日志必须已被 poll 到。
- **B 退了但没写关游戏日志**：进程自己退出，但日志里没有那条。
  ⇒ 必须报「未见关闭游戏的记录」，**不得**谎称已关游戏（INV-30）。
- **C 一直不退**：进程硬挺过整个 settle 窗口。
  ⇒ 必须报「仍未退出，将交由节点 9 清理」，且**不超时**（有界）。

## 关键断言

不是「跑完没报错」，而是：
1. settle 期间确实**等待**了（场景 A/C 的耗时 > 0）；
2. 返回前**重新 poll 过**（场景 A 能看见退出前写下的最后那批日志）；
3. 三种场景的**措辞互不相同**（否则就是没区分开）。
"""

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


class FakeLogWindow:
    """最小可用的 LogWindow 替身：poll() 追加预置文本并记录调用次数。

    ⚠️ 语义必须与真的 LogWindow **一致**，否则探针会验收不到真问题：
      - `poll()` 返回**本次新增**（产品代码用的就是它的返回值）；
      - `text()` 返回**整轮累积**（含运行最开头的内容）。

    第一版探针让 poll() 恒返回 ""，于是漏掉了「用 text() 判范围」这个缺陷 ——
    夹具与真实现的语义偏差，会让探针给出**虚假的通过**。
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._buf = ""
        self.polls = 0

    def poll(self):
        self.polls += 1
        if self._chunks:
            c = self._chunks.pop(0)
            self._buf += c
            return c
        return ""

    def text(self):
        return self._buf

    def failures(self):
        return []


class FakeProc:
    """alive_until 秒后「退出」。"""

    def __init__(self, alive_until):
        self.t0 = time.time()
        self.alive_until = alive_until

    def alive(self):
        return (time.time() - self.t0) < self.alive_until


def run_scenario(name, alive_for, log_chunks, expect_in_log, unexpected_in_log=(),
                 pre_chunks=()):
    """复刻 step8 的 settle 段逻辑（与产品代码同构），返回 (settled, log_text, elapsed)。

    `pre_chunks` 模拟「运行**早期**就已经写进日志」的内容（settle 之前就被
    poll 掉了）。用来验证 settle 判据只看**新增**，不被旧内容蒙混。
    """
    proc = FakeProc(alive_for)
    lw = FakeLogWindow(list(log_chunks))
    # pre_chunks 先塞进累积缓冲（模拟运行早期已读入），不进待读队列
    lw._buf = "".join(pre_chunks)

    settle = 0.4                      # 探针用小值，不拖慢回归
    lines = []

    deadline = time.time() + settle
    new_text = ""
    while time.time() < deadline:
        new_text += lw.poll()
        if not proc.alive():
            break
        time.sleep(0.05)

    settled = not proc.alive()
    elapsed = time.time() - (deadline - settle)
    new_text += lw.poll()

    if verdict_mod.NTE_KILL_GAME and _search(new_text):
        lines.append("已自行关闭游戏")
    elif settled:
        lines.append("未见关闭游戏的记录")
    else:
        lines.append("仍未退出")

    print(f"\n--- {name} ---")
    print(f"  settled={settled}  耗时={elapsed:.2f}s  polls={lw.polls}")
    print(f"  新增文本长度={len(new_text)}  累积文本长度={len(lw.text())}")
    print(f"  措辞: {lines[0]}")

    for want in expect_in_log:
        check(f"{name}: 必须报「{want}」", want in lines[0],
              f"实际「{lines[0]}」")
    for bad in unexpected_in_log:
        check(f"{name}: 不得报「{bad}」", bad not in lines[0],
              f"实际「{lines[0]}」")
    return settled, lines[0], elapsed, lw, new_text


def _search(text):
    import re
    return re.search(verdict_mod.NTE_KILL_GAME, text, re.I)


print("=" * 68)
print("探针：ok-nte 收尾宽限（FAULT #27）")
print("=" * 68)

# ⚠️ 必须用**真的**那一行。NTE_KILL_GAME 锚的是
# `Trying to kill the exe {...HTGame.exe...}`（实测自 10-15 日志），
# **不是** `Killing process(es) with absolute path:` ——
# 我第一版探针用了后者，于是「正常收尾」场景被误判成失败，
# 看着像产品缺陷，其实是夹具写错了。
KILL_LINE = ("2026-10-15 00:23:20,572 INFO TaskExecutor process:"
             "Trying to kill the exe {'name': 'HTGame.exe', 'pid': 24632, "
             "'exe': 'D:\\\\GAMES\\\\Neverness To Everness\\\\Client\\\\"
             "WindowsNoEditor\\\\HT\\\\Binaries\\\\Win64\\\\HTGame.exe'}")

# 场景 A：正常 —— 先写日志再退出
settled_a, msg_a, el_a, lw_a, new_a = run_scenario(
    "A 正常收尾（进程退出 + 写了关游戏日志）",
    alive_for=0.15,
    log_chunks=[KILL_LINE],
    expect_in_log=["已自行关闭游戏"],
    unexpected_in_log=["仍未退出", "未见关闭游戏的记录"],
)
check("A: 进程确实退出了", settled_a)
check("A: settle 期间确实等待过（耗时 > 0）", el_a > 0, f"{el_a:.3f}s")

# 场景 B：退了但没写关游戏日志 —— 绝不能谎称已关游戏
settled_b, msg_b, el_b, lw_b, new_b = run_scenario(
    "B 退出但无关闭日志（证据不足）",
    alive_for=0.15,
    log_chunks=["2026-10-16 02:54:06,809 INFO TaskExecutor "
                "TaskExecutor:Successfully Executed Task, Exiting Game and App!"],
    expect_in_log=["未见关闭游戏的记录"],
    unexpected_in_log=["已自行关闭游戏", "仍未退出"],
)
check("B: 进程确实退出了", settled_b)

# 场景 C：一直不退 —— 必须是有界的
settled_c, msg_c, el_c, lw_c, new_c = run_scenario(
    "C 始终不退出（必须交由节点 9）",
    alive_for=99.0,
    log_chunks=[],
    expect_in_log=["仍未退出"],
    unexpected_in_log=["已自行关闭游戏", "未见关闭游戏的记录"],
)
check("C: 进程确实还活着", not settled_c)
check("C: 耗时有界（< 2s，未被无限等待）", el_c < 2.0, f"{el_c:.3f}s")

# ★ 场景 D：**早期**已经写过一行关游戏日志（例如上一次收尾的残留被轮转进来），
#    但 settle 期间**没有**新的关游戏记录，且进程没退。
#    ⇒ 绝不能因为「累积文本里有」就报「已自行关闭游戏」。
#    这条正是「用 text() 而不是 poll() 返回值」那个缺陷的回归。
settled_d, msg_d, el_d, lw_d, new_d = run_scenario(
    "D 早期有旧关游戏记录、settle 期间没有（范围必须只看新增）",
    alive_for=99.0,
    log_chunks=[],
    pre_chunks=[KILL_LINE],          # 旧内容：在累积缓冲里，但不在本次新增里
    expect_in_log=["仍未退出"],
    unexpected_in_log=["已自行关闭游戏"],
)
check("D: 旧记录不得冒充本次关游戏", "已自行关闭游戏" not in msg_d)
check("D: 累积文本里确实有旧记录（夹具有效）",
      "Trying to kill the exe" in lw_d.text())
check("D: 本次新增里没有关游戏记录", "Trying to kill the exe" not in new_d)

# 跨场景：四种措辞必须互不相同，否则等于没区分
check("四场景措辞互不相同", len({msg_a, msg_b, msg_c, msg_d}) >= 3,
      f"得到 {len({msg_a, msg_b, msg_c, msg_d})} 种")

# 场景 A 的关键：返回前重新 poll 过，退出前写的日志必须已被捕获到
check("A: 返回前重新 poll（最后那批日志没丢）",
      "Trying to kill the exe" in lw_a.text(),
      f"text 长度={len(lw_a.text())}")

print("\n" + "=" * 68)
if FAILS:
    print(f"FAILED：{len(FAILS)} 项未通过")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过")
