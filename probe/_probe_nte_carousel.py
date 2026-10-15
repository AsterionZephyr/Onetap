# -*- coding: utf-8 -*-
"""探测：ok-nte 内容区那条全宽图片轮播是**瞬态**还是**常驻**。

背景：抓到的第一帧（nte-page-00.png）中部被一条全宽图片轮播盖住，
挡住了第 4~9 个任务行。若它是启动动画，等几秒就会消失；
若是常驻面板，就必须找别的办法（滚动 / 关掉）。

用法：
    python -X utf8 probe/_probe_nte_carousel.py [次数] [间隔秒]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from orchestrator import capture, programs, window

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0

OUT = ROOT / "logs/shots"


def band_profile(im):
    """按行统计亮像素，粗看内容区是否被大面积图片占据。"""
    g = im.mean(axis=2)
    h, w = g.shape
    rows = (g > 60).sum(axis=1)
    return h, w, rows


def main():
    w = window.find_window(program=programs.NTE)
    print(f"窗口 = {w}")
    if not w:
        print("[NG] ok-nte 未运行")
        return 1
    hwnd = w["hwnd"]

    prev = None
    for i in range(N):
        f = capture.grab_frame(hwnd)
        p = OUT / f"nte-poll-{i:02d}.png"
        Image.fromarray(f.rgb).save(p)
        im = f.rgb
        h, wd, rows = band_profile(im)
        # 只看中段（排除标题栏与侧栏）
        mid = rows[int(h * 0.25):int(h * 0.9)]
        print(f"[{i}] {f.width}x{f.height} 均值{f.stats['mean_rgb']} "
              f"色彩{f.stats['distinct_colors_sampled']} "
              f"中段平均亮行像素={mid.mean():.0f} -> {p.name}")
        if prev is not None:
            diff = float(np.abs(im.astype(int) - prev.astype(int)).mean())
            print(f"     与上一帧差异 = {diff:.3f}")
        prev = im
        if i < N - 1:
            time.sleep(GAP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
