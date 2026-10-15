# -*- coding: utf-8 -*-
"""探测：ok-nte 任务页的行几何与「开始」按钮位置（v1.4.14）。

实测（nte-clean.png 1500x1000）：
  - 任务行有复选框（青色 20x20 @ x=202..221），行距恒 62px
  - 底部右侧有唯一「开始」按钮
本脚本把行中心与按钮框精确量出来，供编排使用。

用法：
    python -X utf8 probe/_probe_nte_geom.py [帧路径]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

FRAME = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "logs/shots/nte-clean.png")


def runs_of(mask, offset=0, minlen=1):
    out, y, n = [], 0, len(mask)
    while y < n:
        if mask[y]:
            y0 = y
            while y < n and mask[y]:
                y += 1
            if y - y0 >= minlen:
                out.append((y0 + offset, y - 1 + offset))
        else:
            y += 1
    return out


def main():
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    h, w, _ = im.shape
    print(f"帧 {w} x {h}")
    R, G, B = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
    cyan = (G > 150) & (B > 150) & (R < 130)

    print("\n=== 复选框（青色 20x20，x 限定 150..260）===")
    cb = cyan[:, 150:260]
    spark = cb.sum(axis=1) >= 8
    boxes = []
    for a, b in runs_of(spark, minlen=8):
        sub = cb[a:b + 1]
        c = np.where(sub.sum(axis=0) > 0)[0]
        boxes.append((a, b, c.min() + 150, c.max() + 150))
        print(f"  y={a:4d}..{b:4d} 高={b-a+1:2d} 中心={(a+b)/2:6.1f} "
              f"x={c.min()+150}..{c.max()+150}")
    if len(boxes) >= 2:
        cents = [(a + b) / 2 for a, b, _, _ in boxes]
        gaps = [round(cents[i + 1] - cents[i], 1) for i in range(len(cents) - 1)]
        print(f"  行距 = {gaps}")

    print("\n=== 底部「开始」按钮（青色，y>900）===")
    bot = cyan[900:, :]
    cols = np.where(bot.sum(axis=0) > 2)[0]
    rows = np.where(bot.sum(axis=1) > 2)[0]
    if len(cols) and len(rows):
        print(f"  y={rows.min()+900}..{rows.max()+900}  x={cols.min()}..{cols.max()}")
        # 分列簇
        cspark = bot.sum(axis=0) >= 2
        for a, b in runs_of(cspark, minlen=4):
            if b - a >= 20:
                r2 = np.where(bot[:, a:b + 1].sum(axis=1) > 0)[0]
                print(f"    列簇 x={a}..{b} 宽={b-a+1}  y={r2.min()+900}..{r2.max()+900}")

    print("\n=== 底部左侧按钮（取消全选 / 全部展开）—— 白色描边 ===")
    wbox = (R > 200) & (G > 200) & (B > 200)
    bot2 = wbox[900:, :700]
    cols2 = np.where(bot2.sum(axis=0) > 2)[0]
    if len(cols2):
        print(f"  x={cols2.min()}..{cols2.max()}")


if __name__ == "__main__":
    main()
