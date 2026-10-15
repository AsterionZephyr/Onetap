# -*- coding: utf-8 -*-
"""FAULT #23 / #24 回归探针。

背景（两个都是**实测踩到**的，不是假想）：

FAULT #23 —— `click_and_confirm` 原来用「整帧平均像素差 >= 0.5」判断点击是否生效。
  实测 ok-nte 点「开始」后只弹一个顶部 toast「启动成功」，占全帧 0.5% 像素，
  整帧均值只有 0.153 ⇒ 判「画面几乎未变」⇒ 白烧 3 次重试。
  **而那次点击真的成功了**（ok-nte 日志随即开始启动游戏）。
  修复：`frame_changed()` 三分判据（整帧 / 最大 8x8 块 / 变化像素占比）。

FAULT #24 —— `window.running(prog=...)` 关键字名错（签名是 `program=`），
  在 ok-nte 等待循环第一次迭代即抛 TypeError。

本探针的**核心价值**：用当初**误判的那两对真实帧**做回归。
如果日后有人把 `frame_changed` 改回只看整帧均值，这里会立刻红。

用法：D:\\WORKs\\Anaconda\\python.exe -X utf8 probe\\_probe_frame_changed.py
"""
import inspect
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import window                      # noqa: E402
from orchestrator.steps import step8_run_task as s8  # noqa: E402

RESULTS = []


def check(name, got, want, note=""):
    ok = got == want
    RESULTS.append(ok)
    flag = "[PASS]" if ok else "[FAIL]"
    print(f"  {flag} {name}")
    print(f"         实际={got!r} 期望={want!r}" + (f"  {note}" if note else ""))


def load(p):
    from PIL import Image
    return np.asarray(Image.open(str(p)).convert("RGB"))


# 当初误判的那次运行
RUN = ROOT / "logs" / "runs" / "run-20261016-011008" / "shots"


def main():
    print("=" * 72)
    print("FAULT #23 —— frame_changed 三分判据")
    print("=" * 72)

    pairs = [
        ("003-about-to-click.png", "004-no-change-try1.png",
         "try1：右下开始按钮按下态（最大块 5.12@块(7,7)）"),
        ("005-about-to-click.png", "006-no-change-try2.png",
         "try2：顶部 toast「启动成功」（最大块 3.20@块(0,3)）"),
    ]
    have = all((RUN / a).exists() and (RUN / b).exists() for a, b, _ in pairs)
    if not have:
        print(f"  [SKIP] 找不到真实帧 {RUN} —— 跳过真帧回归")
    else:
        for a, b, desc in pairs:
            fa, fb = load(RUN / a), load(RUN / b)
            ch, why = s8.frame_changed(fa, fb)
            print(f"\n  {desc}")
            print(f"        {why}")
            check(f"{a} vs {b} 应判「有变化」", ch, True,
                  "（修复前整帧均值 0.15/0.23 < 0.5 ⇒ 误判为未变化）")

        # 负向：同一帧必须判「无变化」，否则就是无脑放行
        same = load(RUN / "006-no-change-try2.png")
        ch, why = s8.frame_changed(same, same)
        print(f"\n  负向：同一帧")
        print(f"        {why}")
        check("同一帧应判「无变化」", ch, False, "（防无脑放行）")

    # 负向：合成极小扰动（1 个像素）不应被当成「点击生效」
    print("\n  负向：只改 1 个像素（应仍判「无变化」）")
    base = np.full((200, 300, 3), 60, dtype=np.uint8)
    tiny = base.copy()
    tiny[10, 10] = [255, 255, 255]
    ch, why = s8.frame_changed(base, tiny)
    print(f"        {why}")
    check("单像素扰动应判「无变化」", ch, False)

    # 正向：纯局部大变化（一个 20x20 白块）必须被抓到 —— ok-nte toast 的形状
    print("\n  正向：插入 20x20 白块（模拟 toast，整帧占比 0.67%）")
    toast = base.copy()
    toast[5:25, 100:120] = [255, 255, 255]
    ch, why = s8.frame_changed(base, toast)
    print(f"        {why}")
    check("局部白块应判「有变化」", ch, True,
          "（整帧均值只有 ~0.67，旧判据必然漏）")

    # 正向：整页切换（ok-ww 导航那种）也必须继续被原判据抓到
    print("\n  正向：整页由暗变亮（模拟 ok-ww 页面切换）")
    page = np.full((200, 300, 3), 200, dtype=np.uint8)
    ch, why = s8.frame_changed(base, page)
    print(f"        {why}")
    check("整页切换应判「有变化」", ch, True, "（第一判据覆盖）")

    # 正向：帧尺寸改变
    print("\n  正向：帧尺寸改变（窗口重建）")
    ch, why = s8.frame_changed(base, np.full((400, 600, 3), 60, dtype=np.uint8))
    print(f"        {why}")
    check("尺寸改变应判「有变化」", ch, True)

    print()
    print("=" * 72)
    print("FAULT #24 —— window.running 关键字名")
    print("=" * 72)
    sig = inspect.signature(window.running)
    params = list(sig.parameters)
    print(f"  window.running 签名 = {sig}")
    check("running 的形参名应为 'program'", "program" in params, True,
          f"实到形参 {params}")
    check("running 不应有 'prog' 形参", "prog" in params, False)

    # 真正调用一次，确认关键字可用（这正是当初崩掉的那一行）
    print("\n  实际调用 window.running(program=programs.NTE) —— 当初崩掉的写法")
    try:
        from orchestrator import programs
        got = window.running(program=programs.NTE)
        print(f"        -> {got if got else '（未运行）'}")
        check("调用不抛 TypeError", True, True)
    except TypeError as e:
        check("调用不抛 TypeError", f"TypeError: {e}", True)

    # 反向确认：旧的 prog= 写法现在应当报错 —— 证明修复确实改变了行为
    print("\n  反向：旧写法 window.running(prog=...) 现在应抛 TypeError")
    try:
        window.running(prog=None)
        check("旧写法应抛 TypeError", False, True, "（居然没抛，说明又改回去了？）")
    except TypeError:
        check("旧写法应抛 TypeError", True, True)

    print()
    print("=" * 72)
    n_ok = sum(RESULTS)
    print(f"总判定：{'✅ 全部通过' if n_ok == len(RESULTS) else '❌ 有失败'} "
          f"({n_ok}/{len(RESULTS)})")
    print("=" * 72)
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
