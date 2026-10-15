# -*- coding: utf-8 -*-
"""探测：当前 ok-nte 窗口状态 + 身份校验 + 是否被遮挡。

用途：在抓帧前后确认「抓到的到底是不是 ok-nte」，并把遮挡者揪出来。

用法：
    python -X utf8 probe/_probe_nte_state.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from orchestrator import capture, input as input_mod, match, programs, win32, window


def main():
    print("=== 目标窗口 ===")
    for p in programs.ALL:
        print(f"  {p.key:4s} find_window = {window.find_window(program=p)}")
        print(f"       running     = {window.running(program=p)}")

    w = window.find_window(program=programs.NTE)
    if not w:
        print("[NG] ok-nte 未运行")
        return 1
    hwnd = w["hwnd"]
    rect = win32.get_window_rect(hwnd)
    rl, rt = rect.left, rect.top
    rw, rh = rect.right - rect.left, rect.bottom - rect.top
    print(f"\n  rect = ({rl},{rt})-({rect.right},{rect.bottom})  {rw}x{rh}")

    fg = win32.foreground_hwnd()
    print(f"  当前前台 hwnd = {fg}")
    try:
        fgt = win32.get_window_text(fg)
    except Exception as e:
        fgt = f"(读取标题失败 {e})"
    print(f"  当前前台标题 = {fgt!r}")
    print(f"  前台就是 ok-nte 吗 = {fg == hwnd}")

    cx = rl + rw // 2
    cy = rt + rh // 2
    top = win32.top_window_at(cx, cy)
    print(f"  窗口中心 ({cx},{cy}) 处最顶层 hwnd = {top}")
    if top != hwnd:
        try:
            print(f"      遮挡者标题 = {win32.get_window_text(top)!r}")
        except Exception as e:
            print(f"      (读标题失败 {e})")

    print("\n=== 抓帧 + 身份校验 ===")
    f = capture.grab_frame(hwnd)
    print(f"  帧 {f.width}x{f.height} 均值{f.stats['mean_rgb']} 色彩{f.stats['distinct_colors_sampled']}")
    ident = match.verify_identity(f.rgb)
    print(f"  身份 = {ident}")

    out = ROOT / "logs/shots/nte-state.png"
    Image.fromarray(f.rgb).save(out)
    print(f"  落盘 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
