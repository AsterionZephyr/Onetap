"""FAULT #35 回归：抢前台的最后一手（真实点击夺取激活）

背景（实测 2026-10-17）
----------------------
游戏窗口（异环，类 `UnrealWindow`）占住前台时，`win32.set_foreground` 的三手段
（裸调 / AttachThreadInput / ALT 抖动）**全部无效且永不成功**，实测：
  · 节点 7 `--target nte` 实跑 -> `INV-8：置前台失败`，`attempt 1..10` 全败，链条中断；
  · 手工直接调 `set_foreground` 连试 3 次 -> 全 False，前台一直停在游戏 hwnd；
  · **把游戏最小化也不释放**前台（`IsIconic=True` 时前台仍是它）。
而 HANDOFF §2.2 第 5 条早就写了「窗口拉不到前台时，**真实鼠标点击窗口体**能拿到激活」——
但 `input.ensure_foreground` 此前**从未实现这一手**，于是必然以 INV-8 收场。

修法
----
`orchestrator/input.py` 新增 `_click_to_activate(hwnd, log=None)`，并在
`ensure_foreground` 的**重试循环之外**（即 API 手段全部用尽后）调用一次。

本探针分三层
------------
[1] 静态：接线是否真的接上（`_click_to_activate` 存在、被 `ensure_foreground` 调用、
    调用点在循环之外、异常文案已更新、点击点是窗口体顶部而非关闭按钮）。
[2] 语义：用假的 win32 打桩，验证「API 全败 -> 点击 -> 成功」这条路径**确实会走到**，
    以及「点击也没用 -> 仍然抛 GuardFailure」不会被吞掉。
[3] 真实点击几何：只读现场，算一遍 `_click_to_activate` 会点到哪里，
    断言该点落在窗口 rect 内、且**离右上角按钮区足够远**。

跑法（在仓库根）：
    python -X utf8 probe/_probe_foreground_click.py
    python -X utf8 probe/_probe_foreground_click.py --static   # 只跑 [1][2]
"""

import ast
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SRC = os.path.join(ROOT, "orchestrator", "input.py")

_pass = 0
_fail = 0


def ck(cond, label, extra=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"    \u2705 {label}")
    else:
        _fail += 1
        print(f"    \u274c {label}" + (f"  \u2014\u2014 {extra}" if extra else ""))


def main():
    print("=" * 74)
    print("FAULT #35 \u56de\u5f52\uff1a\u62a2\u524d\u53f0\u7684\u6700\u540e\u4e00\u624b\uff08\u771f\u5b9e\u70b9\u51fb\u593a\u53d6\u6fc0\u6d3b\uff09")
    print("=" * 74)

    text = open(SRC, encoding="utf-8").read()
    tree = ast.parse(text)

    # ---------------------------------------------------------------- [1] 静态
    print("\n[1] \u63a5\u7ebf\uff1a\u6700\u540e\u4e00\u624b\u662f\u5426\u771f\u7684\u63a5\u4e0a\u4e86")
    ck("def _click_to_activate(" in text,
       "\u5b58\u5728 _click_to_activate\uff08\u65b0\u589e\u7684\u7b2c\u4e09\u6761\u901a\u9053\uff09")

    # _click_to_activate 的 body
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_click_to_activate":
            fn = node
            break
    ck(fn is not None, "AST \u91cc\u627e\u5f97\u5230 _click_to_activate \u5b9a\u4e49")

    # ensure_foreground 的 body
    ef = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "ensure_foreground":
            ef = node
            break
    ck(ef is not None, "AST \u91cc\u627e\u5f97\u5230 ensure_foreground \u5b9a\u4e49")

    if fn is not None and ef is not None:
        # ensure_foreground 必须在**循环之外**调用 _click_to_activate。
        # 判据：包含 _click_to_activate 调用的那一层，不能同时是 for 循环体。
        call_lines = []
        for node in ast.walk(ef):
            if isinstance(node, ast.Call):
                f = node.func
                nm = getattr(f, "id", None) or getattr(f, "attr", None)
                if nm == "_click_to_activate":
                    call_lines.append(node.lineno)
        ck(len(call_lines) == 1,
           f"ensure_foreground \u91cc\u6070\u597d\u8c03\u7528\u4e00\u6b21 _click_to_activate\uff08\u5b9e\u6d4b {len(call_lines)} \u6b21\uff09")

        # 找 for 循环的行号范围，断言调用点不在任何一个 for 体内
        for_ranges = []
        for node in ast.walk(ef):
            if isinstance(node, ast.For):
                lo = min(n.lineno for n in ast.walk(node) if hasattr(n, "lineno"))
                hi = max(n.lineno for n in ast.walk(node) if hasattr(n, "lineno"))
                for_ranges.append((lo, hi))
        in_loop = [ln for ln in call_lines
                   if any(lo <= ln <= hi for lo, hi in for_ranges)]
        ck(not in_loop,
           "\u8c03\u7528\u70b9\u5728\u91cd\u8bd5\u5faa\u73af**\u4e4b\u5916**\uff08\u5b83\u4e0d\u662f\u300c\u518d\u8bd5\u4e00\u6b21 API\u300d\uff0c\u800c\u662f\u6362\u901a\u9053\uff09",
           f"\u547d\u4e2d for \u4f53\u5185\u884c {in_loop}")

        # 调用点必须在**最后那个** raise GuardFailure 之前
        # （循环内还有一个 INV-12 的 raise，不能用 min() —— 那会把结论搞反）
        rais = [n.lineno for n in ast.walk(ef) if isinstance(n, ast.Raise)]
        ck(bool(rais) and max(call_lines) < max(rais),
           "\u8c03\u7528\u70b9\u5728\u6700\u540e\u4e00\u4e2a raise GuardFailure \u4e4b\u524d\uff08\u5426\u5219\u6c38\u8fdc\u8dd1\u4e0d\u5230\uff09",
           f"call@{max(call_lines)} raise@{rais}")

        # 点击后必须验证前台（不能只发点击就宣布成功）
        body_src = ast.get_source_segment(text, fn)
        ck("foreground" in body_src,
           "\u70b9\u51fb\u540e**\u91cd\u65b0\u9a8c\u8bc1** foreground\uff08\u4e0d\u53ea\u53d1\u4e00\u4e0b\u70b9\u51fb\u5c31\u5ba3\u5e03\u6210\u529f\uff09")

        # 必须避开右上角按钮区：x 用宽度的一部分，不能贴右边缘
        # \u26a0\ufe0f \u6ce8\u610f\uff1a\u6e90\u7801\u5199\u7684\u662f st["width"] // 5\uff0c\u4e2d\u95f4\u5939\u7740 `"]`\u3002
        #    \u672c\u63a2\u9488\u6700\u521d\u5199\u6210\u641c `width // 5`\uff0c\u6c38\u8fdc\u547d\u4e2d\u4e0d\u5230 \u2014\u2014 \u5df2\u4fee\u6b63\u3002
        ck('"width"] // 5' in body_src,
           "\u70b9\u51fb\u70b9\u6a2a\u5750\u6807\u504f\u5de6\uff08st[\"width\"] // 5\uff09\uff0c\u907f\u5f00\u53f3\u4e0a\u89d2\u6700\u5927\u5316/\u5173\u95ed\u6309\u94ae")
        ck("min(18" in body_src,
           "\u70b9\u51fb\u70b9\u7eb5\u5750\u6807\u9650\u5728\u7a97\u53e3\u9876\u90e8\uff08min(18,\u2026\uff09\uff0c\u907f\u5f00\u4e3b\u4f53\u63a7\u4ef6")

        # 窗口太小时不点（避免点到奇怪的地方）
        ck('"height"] < 40' in body_src or "height < 40" in body_src,
           "\u7a97\u53e3\u8fc7\u77ee\u65f6\u76f4\u63a5\u653e\u5f03\u70b9\u51fb\uff08\u4e0d\u4e71\u70b9\uff09")

        # 点击异常必须被吞掉（点击失败不该把 GuardFailure 变成别的异常）
        ck("except Exception" in body_src,
           "\u70b9\u51fb\u5f02\u5e38\u88ab\u5305\u4f4f\uff08\u70b9\u4e0d\u4e86\u4e0d\u80fd\u628a INV-8 \u53d8\u6210\u522b\u7684\u5f02\u5e38\uff09")

    # 异常文案必须更新（不能还留着旧的说法让人以为没试过点击）
    ck("真实点击窗口体也未能夺取激活" in text,
       "INV-8 \u6587\u6848\u5df2\u66f4\u65b0\uff08\u8bf4\u660e\u8fde\u771f\u5b9e\u70b9\u51fb\u4e5f\u5931\u8d25\u4e86\uff09")
    ck("ok-ww" not in text,
       "\u6587\u6848\u91cc\u4e0d\u518d\u786c\u7f16\u7801 ok-ww\uff08\u591a\u7a0b\u5e8f\u5171\u7528\uff09")

    # ---------------------------------------------------------------- [2] 语义
    print("\n[2] \u8bed\u4e49\uff1a\u6253\u6869\u9a8c\u8bc1\u300cAPI \u5168\u8d25 -> \u70b9\u51fb -> \u6210\u529f\u300d\u8fd9\u6761\u8def\u8def\u5f84\u771f\u7684\u4f1a\u8d70")
    from orchestrator import input as input_mod

    real_win32 = input_mod.win32

    class FakeWin32:
        def __init__(self, click_works):
            self.click_works = click_works
            self.foreground_reported = False
            self.click_calls = []
            self.setfg_calls = 0

        # --- 被 ensure_foreground 用到的最小面 ---
        def window_state(self, hwnd):
            return {"left": 100, "top": 100, "width": 1500, "height": 1000,
                    "iconic": False, "visible": True,
                    "foreground": self.foreground_reported}

        def is_iconic_sentinel(self, left, top):
            return left == -32000 and top == -32000

        def restore_window(self, hwnd):
            return True

        def set_foreground(self, hwnd):
            self.setfg_calls += 1
            return False                       # 永远失败 —— 模拟 FAULT #35

        def click(self, x, y):
            self.click_calls.append((x, y))
            if self.click_works:
                self.foreground_reported = True

    try:
        # --- 情形 A：点击有效 -> 应当成功 ---
        fake = FakeWin32(click_works=True)
        input_mod.win32 = fake
        st = input_mod.ensure_foreground(1234, tries=3, interval=0.01, log=None)
        ck(st and st["foreground"] is True,
           "API \u5168\u8d25\u65f6\uff0c\u771f\u5b9e\u70b9\u51fb\u53d6\u5f97\u524d\u53f0 -> ensure_foreground \u6210\u529f\u8fd4\u56de")
        ck(fake.setfg_calls >= 3,
           f"API \u786e\u5b9e\u88ab\u8bd5\u8fc7\u591a\u6b21\uff08{3} \u6b21\uff09\u624d\u9000\u5230\u70b9\u51fb")
        ck(len(fake.click_calls) == 1,
           f"\u70b9\u51fb\u6070\u597d\u53d1\u751f 1 \u6b21\uff08\u5b9e\u6d4b {len(fake.click_calls)}\uff09")
        if fake.click_calls:
            x, y = fake.click_calls[0]
            ck(100 <= x <= 1600 and 100 <= y <= 1100,
               f"\u70b9\u51fb\u70b9 ({x},{y}) \u5728\u7a97\u53e3 rect \u5185")

        # --- 情形 B：点击也没用 -> 必须抛 GuardFailure，不能被吞 ---
        fake2 = FakeWin32(click_works=False)
        input_mod.win32 = fake2
        raised = None
        try:
            input_mod.ensure_foreground(1234, tries=2, interval=0.01, log=None)
        except Exception as e:                                  # noqa: BLE001
            raised = e
        ck(raised is not None,
           "\u70b9\u51fb\u4e5f\u65e0\u6548\u65f6**\u4ecd\u7136\u629b\u5f02\u5e38**\uff08\u4e0d\u4f1a\u9759\u9ed8\u653e\u884c\uff09")
        ck(raised is not None and "INV-8" in str(raised),
           "\u629b\u7684\u662f INV-8\uff08\u8c03\u7528\u65b9\u80fd\u8bc6\u522b\uff09",
           str(raised))
        ck(len(fake2.click_calls) == 1,
           "\u5931\u8d25\u8def\u5f84\u4e0a\u4e5f\u53ea\u70b9\u4e00\u6b21\uff08\u4e0d\u4f1a\u72c2\u70b9\uff09")
    finally:
        input_mod.win32 = real_win32

    # ---------------------------------------------------------------- [3] 几何
    if "--static" in sys.argv:
        print("\n[3] \u771f\u5b9e\u51e0\u4f55\uff1a\u8df3\u8fc7\uff08--static\uff09")
    else:
        print("\n[3] \u771f\u5b9e\u51e0\u4f55\uff1a\u53ea\u8bfb\u73b0\u573a\uff0c\u7b97\u4e00\u904d\u4f1a\u70b9\u5230\u54ea\u91cc")
        from orchestrator import programs, window, win32
        for prog in programs.ALL:
            # find_window 返回的是 dict\uff08\u5e26 'hwnd'\uff09\uff0c\u51e0\u4f55\u8981\u53e6\u53d6
            info = window.find_window(prog)
            if not info:
                print(f"    - {prog.display}: \u672a\u8fd0\u884c\uff0c\u8df3\u8fc7")
                continue
            st = win32.window_state(info["hwnd"])
            if st is None:
                print(f"    - {prog.display}: window_state \u8bfb\u4e0d\u5230\uff0c\u8df3\u8fc7")
                continue
            L, T = st["left"], st["top"]
            W, H = st["width"], st["height"]
            x = L + max(20, W // 5)
            y = T + min(18, H // 8)
            print(f"    {prog.display}: rect=({L},{T}) {W}x{H} -> \u4f1a\u70b9 ({x},{y})")
            ck(L <= x <= L + W and T <= y <= T + H,
               f"{prog.display}\uff1a\u70b9\u51fb\u70b9\u5728\u7a97\u53e3 rect \u5185")
            ck(x < L + W - 200,
               f"{prog.display}\uff1a\u79bb\u53f3\u8fb9\u7f18 >= 200px\uff08\u907f\u5f00\u53f3\u4e0a\u89d2\u6309\u94ae\uff09",
               f"x={x}, \u53f3\u8fb9={L+W}")
            ck(y < T + 60,
               f"{prog.display}\uff1a\u70b9\u5728\u7a97\u53e3\u9876\u90e8 60px \u5185\uff08\u6807\u9898\u680f\u533a\uff09",
               f"y={y}, top={T}")

    print("\n" + "=" * 74)
    print(f"\u7ed3\u679c\uff1a{_pass} \u9879\u901a\u8fc7\uff0c{_fail} \u9879\u5931\u8d25")
    print("=" * 74)
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
