# -*- coding: utf-8 -*-
"""探测：ok-nte 任务页每行长什么样 —— 逐行裁图落盘，便于人眼核对。

用于查清「羁遇赠礼」那行为什么没检出青色复选框（未勾选？还是被裁掉？），
以及每行文字是否可读（决定能否按任务名定位）。

用法：
    python -X utf8 probe/_probe_nte_rowcrop.py [帧路径]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

FRAME = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "logs/shots/nte-clean.png")
OUT = ROOT / "logs/shots"


def main():
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    h, w, _ = im.shape
    print(f"帧 {w}x{h}")
    g = im.astype(int).mean(axis=2)
    R, G, B = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)

    print("\n=== 逐行检查 y=140..720 的复选框区域（x=195..230）===")
    for y in range(140, 720, 1):
        row = im[y, 195:230]
        cy = (row[:, 1].astype(int) > 150) & (row[:, 2].astype(int) > 150) & (row[:, 0].astype(int) < 130)
        # 白色勾选
        wh = (row[:, 0] > 200) & (row[:, 1] > 200) & (row[:, 2] > 200)
        if cy.sum() or wh.sum():
            pass
    # 按行汇总成簇
    def runs(mask, off=0, minlen=1):
        out, y, n = [], 0, len(mask)
        while y < n:
            if mask[y]:
                y0 = y
                while y < n and mask[y]:
                    y += 1
                if y - y0 >= minlen:
                    out.append((y0 + off, y - 1 + off))
            else:
                y += 1
        return out

    for label, mask in (("青底", (G > 150) & (B > 150) & (R < 130)),
                        ("白勾", (R > 200) & (G > 200) & (B > 200))):
        sub = mask[:, 195:230]
        spark = sub.sum(axis=1) >= 3
        print(f"\n  [{label}] x=195..230 的簇：")
        for a, b in runs(spark, minlen=5):
            if a < 750:
                print(f"    y={a:4d}..{b:4d} 高={b-a+1:2d} 中心={(a+b)/2:6.1f}")

    print("\n=== 落盘：每行整条裁图（x=140..1500），行距 62，从 y=140 起 ===")
    names = ["row0", "row1", "row2", "row3", "row4", "row5", "row6", "row7"]
    tops = [140, 254, 316, 378, 440, 502, 564, 626]
    for nm, t in zip(names, tops):
        c = im[t:t + 66, 140:1500]
        p = OUT / f"nte-{nm}.png"
        Image.fromarray(c).save(p)
        # 该行是否有青色
        cc = c[:, :, 1].astype(int) > 150
        ccc = cc & (c[:, :, 2].astype(int) > 150) & (c[:, :, 0].astype(int) < 130)
        print(f"  {nm}: y={t}..{t+66}  青色像素={int(ccc.sum()):4d} -> {p.name}")


if __name__ == "__main__":
    main()
