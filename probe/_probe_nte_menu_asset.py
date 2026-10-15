# -*- coding: utf-8 -*-
"""探测：把实时帧里 ok-nte 的 ☰ 原样取出来，与既有模板逐像素对照。

目的：`4_nte_menu.png`（登记为「ok-nte ☰ 身份锚点 v1.4.8」）在 v1.4.14 帧上
只得 0.4481，而 ok-ww 的 `3_ww_menu.png` 却得 1.0000。判明到底是谁错了：
是程序改版，还是当初这个资产本身就**裁错了**。

用法：
    python -X utf8 probe/_probe_nte_menu_asset.py [帧路径]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

FRAME = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "logs/shots/nte-page-00.png")
TPL = ROOT / "templates"


def ascii_of(gray, thr=140):
    return ["".join("1" if v > thr else "0" for v in row) for row in gray]


def main():
    frame = np.asarray(Image.open(FRAME).convert("RGB"))
    print(f"帧 {frame.shape[1]}x{frame.shape[0]}")
    print()
    print("=== 帧中 ☰ 所在区域 y=52..76, x=8..44 的灰度矩阵（先做列裁剪定位真实字形）===")
    g = frame[:, :, :3].mean(axis=2)
    sub = g[50:78, 0:50]
    for i, row in enumerate(ascii_of(sub)):
        print(f"  y={50+i:3d} {row}")

    print()
    print("=== 真实 ☰ 的三条线几何 ===")
    for y in range(50, 78):
        xs = np.where(g[y, 0:50] > 140)[0]
        if len(xs):
            print(f"  y={y:3d} n={len(xs):2d} x={xs.min():2d}..{xs.max():2d}")

    print()
    for name in ("3_ww_menu.png", "4_nte_menu.png"):
        tpl = np.asarray(Image.open(TPL / name).convert("RGB"))
        tg = tpl.mean(axis=2)
        print(f"=== {name}  {tpl.shape[1]}x{tpl.shape[0]} ===")
        for row in ascii_of(tg):
            print(f"    {row}")
        ys, xs = np.where(tg > 140)
        if len(ys):
            bar_lens = []
            for y in range(tg.shape[0]):
                xr = np.where(tg[y] > 140)[0]
                if len(xr):
                    bar_lens.append((y, len(xr), xr.min(), xr.max()))
            print(f"    亮像素 bbox y={ys.min()}..{ys.max()} x={xs.min()}..{xs.max()}")
            for y, n, a, b in bar_lens:
                print(f"      行 y={y:2d} 长={n:2d} x={a}..{b}")
        print()


if __name__ == "__main__":
    main()
