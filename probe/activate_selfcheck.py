"""probe/activate_selfcheck.py — 置前台「真实点击夺取激活」的离线自检。

为什么存在：FAULT #36（2026-10-19 03:20 实测，MaaEnd）。MaaEnd 跑完后它自己拉起
的鹰角启动器抢在前台、盖住 MaaEnd 约 95% 且线程不响应，于是
SetForegroundWindow 永久失败；旧的兜底实现**固定**点左上 1/5、顶部 18px，
那一点正好落在启动器上 —— 真实点击把激活交给了别的程序（违反 INV-23 的本意），
MaaEnd 永远拿不到前台，框架只能报 INV-8。

本自检用假 win32（无真实窗口、无光标）验证四条：
  A. 首选点被遮挡时，能自动退到未被遮挡的候选点并点击；
  B. 抬 Z 序（raise_window）后首选点可用时，就点首选点（顺序没变）；
  C. 整块被遮挡时**一次都不点**，并如实说出遮挡者；
  D. covering_window 能报出遮挡窗口的 hwnd + 标题；
  E. 窗口**已经销毁**（window_state 返回 None）时不点，且日志说明是「窗口没了」
     —— 陷阱 17：静默 return False 会让外层误报成「置前台失败」（2026-10-19 05:21 ok-ww 自我更新）。

跑法：python probe\activate_selfcheck.py   （exit 0 = 全过）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import input as input_mod                      # noqa: E402

TARGET = 1
COVER = 999
RECT = {"left": 759, "top": 338, "width": 1201, "height": 826}   # 实测 MaaEnd
LAUNCHER = (624, 323, 1936, 1077)                               # 实测鹰角启动器


class FakeWin32:
    """只实现 input.py 用到的几个函数。"""

    def __init__(self, cover=(624, 323, 1936, 1077), raise_helps=False,
                 raise_ok=False, gone=False):
        self.cover = cover
        self.gone = gone
        self.raise_helps = raise_helps
        self.raise_ok = raise_ok
        self.raised = False
        self.clicks = []
        self.foreground = False
        self.logs = []

    # --- 被 input.py 调用 ---
    def window_state(self, hwnd):
        if self.gone:
            return None
        st = dict(RECT)
        st["iconic"] = False
        st["visible"] = True
        st["foreground"] = self.foreground
        return st

    def top_window_at(self, x, y):
        if self.raised or not self._covered(x, y):
            return TARGET
        return COVER

    def raise_window(self, hwnd):
        if self.raise_ok:
            self.raised = True
        return self.raise_ok

    def screen_size(self):
        return 2560, 1440

    def click(self, x, y):
        self.clicks.append((x, y))
        if self.top_window_at(x, y) == TARGET:
            self.foreground = True          # 只有当点真的落在目标上才拿到激活

    def get_window_text(self, hwnd):
        return "鹰角启动器" if hwnd == COVER else "MaaEnd v2.34.0-beta.1"

    # --- 辅助 ---
    def _covered(self, x, y):
        if self.cover is None:
            return False
        l, t, r, b = self.cover
        return l <= x < r and t <= y < b


def run_case(name, fake):
    input_mod.win32 = fake
    logs = []
    ok = input_mod._click_to_activate(TARGET, log=logs.append)
    return ok, fake.clicks, logs, fake


def main():
    fails = []

    # A：首选点被启动器盖住 -> 必须退到未被遮挡的候选点
    ok, clicks, logs, fake = run_case("A", FakeWin32())
    first = input_mod._activation_candidates(dict(RECT))[0]
    if not ok:
        fails.append("A: 残留遮挡时没拿到激活")
    if not clicks or clicks[0] == first:
        fails.append(f"A: 仍在首选点 {first} 点击（那点被启动器盖住）")
    if clicks and not (clicks[0][0] >= LAUNCHER[2]):
        fails.append(f"A: 点击 {clicks[0]} 仍落在启动器矩形内")
    print(f"A 退让：clicks={clicks} ok={ok}  首选点={first}")

    # B：抬 Z 序后首选点可用 -> 点首选点
    ok, clicks, logs, fake = run_case("B", FakeWin32(raise_ok=True))
    if not ok or not clicks or clicks[0] != first:
        fails.append(f"B: raise 后应点首选点 {first}，实际 clicks={clicks} ok={ok}")
    print(f"B 抬 Z 序：clicks={clicks} ok={ok}")

    # C：整块被遮挡 -> 一次都不点，日志点明遮挡者
    ok, clicks, logs, fake = run_case("C", FakeWin32(cover=(0, 0, 2560, 1440)))
    if ok:
        fails.append("C: 整块被遮挡却报成功")
    if clicks:
        fails.append(f"C: 整块被遮挡却点了 {clicks}（点了就是操作别的程序）")
    if not any("遮挡" in m for m in logs):
        fails.append(f"C: 日志没说遮挡，logs={logs}")
    print(f"C 全遮挡：clicks={clicks} ok={ok} log={logs[-1] if logs else ''}")

    # D：covering_window 报出遮挡者
    input_mod.win32 = FakeWin32()
    cover = input_mod.covering_window(TARGET)
    if not cover or cover[0] != COVER or "启动器" not in cover[1]:
        fails.append(f"D: covering_window 返回 {cover}")
    print(f"D 遮挡诊断：{cover}")

    # E：窗口已销毁 -> 不点，且日志说清「窗口没了」而不是「前置台失败」
    ok, clicks, logs, fake = run_case("E", FakeWin32(gone=True))
    if ok:
        fails.append("E: 窗口已销毁却报成功")
    if clicks:
        fails.append(f"E: 窗口已销毁却点了 {clicks}")
    if not any("窗口" in m and ("销毁" in m or "退出" in m) for m in logs):
        fails.append(f"E: 日志没说窗口已没了，logs={logs}")
    print(f"E 窗口已销毁：clicks={clicks} ok={ok} log={logs[-1] if logs else ''}")

    if fails:
        print("FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS 5/5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
