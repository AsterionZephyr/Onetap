# -*- coding: utf-8 -*-
"""探测：ok-nte 任务页的**行结构**（用于设计行定位策略）。

目标：搞清 v1.4.14 任务页每一行长什么样、行间距多少、行内有几个元素、
「开始」按钮在哪一列。用于替代已过期的 `3_nte_daily.png`。

用法：
    python -X utf8 probe/_probe_nte_rows.py [帧路径]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

FRAME = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "logs/shots/nte-clean.png")


def runs_of(mask, offset=0):
    out, y, n = [], 0, len(mask)
    while y < n:
        if mask[y]:
            y0 = y
            while y < n and mask[y]:
                y += 1
            out.append((y0 + offset, y - 1 + offset))
        else:
            y += 1
    return out


def main():
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    h, w, _ = im.shape
    print(f"帧 {w} x {h}  ({FRAME})")
    g = im.astype(int).mean(axis=2)
    R, G, B = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)

    # 内容区：跳过侧栏 x<135
    x0 = 135
    print(f"\n=== 内容区 x>={x0} 的青色（开始按钮，B/G>150 且 R<130）分布 ===")
    cyan = (G > 150) & (B > 150) & (R < 130)
    cy_sub = cyan[:, x0:]
    cols = np.where(cy_sub.sum(axis=0) > 4)[0]
    rows = np.where(cy_sub.sum(axis=1) > 4)[0]
    if len(cols) and len(rows):
        print(f"  x={cols.min()+x0}..{cols.max()+x0}  y={rows.min()}..{rows.max()}")
        print(f"  青色簇（按行合并）：")
        spark = cy_sub.sum(axis=1) >= 4
        for a, b in runs_of(spark):
            sub = cy_sub[a:b + 1]
            c = np.where(sub.sum(axis=0) > 0)[0]
            print(f"    y={a:4d}..{b:4d} 高={b-a+1:3d}  x={c.min()+x0}..{c.max()+x0}")
    else:
        print("  无")

    print(f"\n=== 内容区行分隔：逐行「与背景不同的像素」数（找行卡片边界）===")
    # 任务行卡片通常有比背景略亮的底色
    bg = np.median(g[:, x0:], axis=1)
    card = (g[:, x0:] > bg[:, None] + 6).sum(axis=1)
    spark = card > (w - x0) * 0.25
    for a, b in runs_of(spark):
        if b - a >= 8:
            print(f"  y={a:4d}..{b:4d}  高={b-a+1:3d}  中心={(a+b)/2:6.1f}")


if __name__ == "__main__":
    main()
