# -*- coding: utf-8 -*-
"""探测：ok-nte 侧栏横向扫描带的逐行亮像素剖面。

目的：find_sidebar_item 在 ok-nte 上只找到 7 项（画面里明显有 13 项），
且行距在 34~47 之间跳动。本脚本把原始剖面打出来，看清到底是
「簇合并阈值」的问题，还是「扫描带 x 范围」根本没覆盖到图标/文字。

用法：
    python -X utf8 probe/_probe_nte_band.py [帧路径]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

FRAME = sys.argv[1] if len(sys.argv) > 1 else r"logs\shots\nte-page-00.png"


def main():
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    g = im.mean(axis=2)
    h, w = g.shape
    print(f"帧 {w} x {h}  ({FRAME})")

    for x0, x1, thr in ((8, 95, 110), (8, 95, 60), (0, 120, 110)):
        print(f"\n=== 扫描带 x={x0}..{x1} thr={thr} —— 簇边界 ===")
        band = g[:, x0:x1]
        spark = (band > thr).sum(axis=1) >= 2
        runs = []
        y = 0
        while y < h:
            if spark[y]:
                y0 = y
                while y < h and spark[y]:
                    y += 1
                runs.append((y0, y - 1))
            else:
                y += 1
        for a, b in runs:
            print(f"  y={a:4d}..{b:4d}  高={b-a+1:3d}  中心={(a+b)/2:6.1f}")
        print(f"  共 {len(runs)} 段")


if __name__ == "__main__":
    main()
