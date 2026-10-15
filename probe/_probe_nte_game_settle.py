"""回归探针：node 8 开工前必须等 ok-nte 把游戏拉起来并稳定（FAULT #28）。

## 为什么需要这个探针

FAULT #28 的现场：ok-nte **窗口一出现就自己去拉游戏**（与「点开始」无关），
游戏全屏后屏幕抓图返回纯黑。节点 8 若正好在这段开工，抓帧全黑 ⇒ INV-13
⇒ 只活 2.4 秒就 FAILED（实测 run-20261016-031137）。

成功与失败**只差时序**：游戏已稳定 ⇒ 一路通；正在起 ⇒ 全黑。

修法：节点 8 在 ok-nte 上开工前先调 `nte_wait_game_settled` ——
先等游戏进程出现，再等画面**连续可读**若干次。

## 本探针测什么

不连真窗口（那要跑真游戏），而是用**替身**验证决策逻辑：

1. 游戏**已在运行** ⇒ 不得再空等「出现」，直接进入可读性检查；
2. 游戏**尚未出现**、随后出现 ⇒ 必须真的等待，并在出现后继续；
3. 画面**始终全黑** ⇒ 必须返回 False（超时），且**不得抛异常**
   （证据不足不臆断 —— 交给既有 INV-13 闸门裁决）；
4. 画面**先黑后亮** ⇒ 必须等到连续可读才返回 True（不能抓到一次就放行）；
5. 等待是**有界**的（不会无限等）。

判据落在「返回值 + 是否真的等待过 + 有界」，而不是「跑完没报错」。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILS = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class FakeStats:
    def __init__(self, mean_rgb):
        self._m = mean_rgb

    def get(self, k, d=None):
        return self._m if k == "mean_rgb" else d


class FakeFrame:
    def __init__(self, mean_rgb=(45, 45, 45)):
        self.stats = FakeStats(mean_rgb)


class FakeGame:
    """appears_after 秒后「游戏进程出现」。"""

    def __init__(self, appears_after):
        self.t0 = time.time()
        self.appears_after = appears_after

    def __call__(self):
        if (time.time() - self.t0) >= self.appears_after:
            return [("HTGame.exe", 1234, "D:\\...\\HTGame.exe")]
        return []


def simulate(game_appears_after, readable_after, *, game_wait=0.5, samples=3,
             poll=0.05, grab_timeout=0.5):
    """与产品代码 nte_wait_game_settled 同构的模拟，参数缩小以便快速回归。"""
    game = FakeGame(game_appears_after)
    sleeps = []
    t0 = time.time()
    got_game = None

    if not game():
        while time.time() - t0 < game_wait:
            if game():
                got_game = time.time() - t0
                break
            sleeps.append(poll)
            time.sleep(poll)
        else:
            return False, {"why": "game never appeared", "waited": time.time() - t0}

    good = 0
    t1 = time.time()
    while time.time() - t1 < game_wait:
        if (time.time() - t0) >= readable_after:
            good += 1
            if good >= samples:
                return True, {"why": "stable", "waited": time.time() - t0,
                              "game_seen_after": got_game, "good": good}
        else:
            good = 0
        sleeps.append(poll)
        time.sleep(poll)

    return False, {"why": "never stable", "waited": time.time() - t0,
                   "game_seen_after": got_game, "good": good}


print("=" * 68)
print("探针：节点 8 等游戏稳定（FAULT #28）")
print("=" * 68)

# 场景 1：游戏已在跑、画面已可读 ⇒ 很快就稳定
ok1, info1 = simulate(game_appears_after=0.0, readable_after=0.0)
print(f"\n--- 1 游戏已在跑、画面可读 ---\n  {info1}")
check("1: 判为稳定", ok1)
check("1: 没有空等『游戏出现』", info1.get("game_seen_after") is None)
check("1: 快（< 0.3s）", info1["waited"] < 0.3, f"{info1['waited']:.2f}s")

# 场景 2：游戏尚未出现，0.15s 后出现，画面随即可读
ok2, info2 = simulate(game_appears_after=0.15, readable_after=0.15)
print(f"\n--- 2 游戏稍后出现 ---\n  {info2}")
check("2: 判为稳定", ok2)
check("2: 确实等待过游戏出现", info2.get("game_seen_after") is not None,
      f"game_seen_after={info2.get('game_seen_after')}")

# 场景 3：画面始终全黑 ⇒ 超时返回 False，且不抛异常
ok3, info3 = simulate(game_appears_after=0.0, readable_after=99.0)
print(f"\n--- 3 画面始终全黑 ---\n  {info3}")
check("3: 判为未稳定（False）", not ok3)
check("3: 有界（< 1.2s，未无限等）", info3["waited"] < 1.2, f"{info3['waited']:.2f}s")
check("3: 返回 False 而非抛异常", ok3 is False)

# 场景 4：游戏一直不出现 ⇒ 超时 False，有界
ok4, info4 = simulate(game_appears_after=99.0, readable_after=99.0)
print(f"\n--- 4 游戏始终不出现 ---\n  {info4}")
check("4: 判为未稳定（False）", not ok4)
check("4: 有界（< 1.2s）", info4["waited"] < 1.2, f"{info4['waited']:.2f}s")

# 场景 5：先黑后亮 —— 必须等到**连续**可读，不能抓一次就放行
ok5, info5 = simulate(game_appears_after=0.0, readable_after=0.2, samples=3)
print(f"\n--- 5 先黑后亮（要连续可读）---\n  {info5}")
check("5: 最终判为稳定", ok5)
check("5: 等到了连续 3 次可读", info5.get("good") == 3, f"good={info5.get('good')}")
check("5: 稳定时刻晚于画面变亮", info5["waited"] >= 0.2, f"{info5['waited']:.2f}s")

# 场景 6：产品代码真的存在且可调用（防止探针与产品脱节）
import inspect  # noqa: E402
from orchestrator.steps import step8_run_task as s8  # noqa: E402

print("\n--- 6 产品代码接口 ---")
check("6: nte_wait_game_settled 存在", hasattr(s8, "nte_wait_game_settled"))
check("6: 常量为正数",
      s8.NTE_GAME_WAIT_SECONDS > 0 and s8.NTE_READABLE_SAMPLES >= 1)
sig = inspect.signature(s8.nte_wait_game_settled)
check("6: 签名是 (state, log)", list(sig.parameters) == ["state", "log"],
      str(sig))
src = inspect.getsource(s8.nte_wait_game_settled)
check("6: 用 game_processes 判游戏出现", "game_processes" in src)
check("6: 用 grab_frame 判画面可读", "grab_frame" in src)
check("6: 超时不抛异常（返回 False）", "return False" in src)

# 场景 7：调用点确实接上了（否则一切白搭）
src_body = inspect.getsource(s8.click_and_confirm)
check("7: click_and_confirm 里调用了它",
      "nte_wait_game_settled" in src_body)
check("7: 只在第 1 轮等（避免重复等待）",
      "attempt == 1" in src_body)
check("7: 离线/dry-run 不等待",
      "args.offline or args.dry_run" in src_body)

print("\n" + "=" * 68)
if FAILS:
    print(f"FAILED：{len(FAILS)} 项未通过")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过")
