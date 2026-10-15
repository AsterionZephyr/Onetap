# -*- coding: utf-8 -*-
"""探测：ok-nte 顶部导航组的选中态（青色高亮）与结构。

背景：ok-nte 侧栏分两组 —— 上组是**页面导航图标**（☰/▶/⏱/▤/🎮），
下组是**任务菜单列表**。FRAMEWORK §0.1.2 记 ok-nte 的按钮高亮色是**青**
（B/G>150 且 R<130），ok-ww 是白。本脚本验证该色判据在真实帧上成立，
并定位「任务页」那个被选中的导航项。

用法：
    python -X utf8 probe/_probe_nte_nav.py [帧路径]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

FRAME = sys.argv[1] if len(sys.argv) > 1 else r"logs\shots\nte-page-00.png"


def runs_of(mask_1d, offset=0):
    out, y = [], 0
    n = len(mask_1d)
    while y < n:
        if mask_1d[y]:
            y0 = y
            while y < n and mask_1d[y]:
                y += 1
            out.append((y0 + offset, y - 1 + offset))
        else:
            y += 1
    return out


def main():
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    h, w, _ = im.shape
    print(f"帧 {w} x {h}  ({FRAME})")

    print("\n=== 顶部区域 x=0..75, y=40..200 的青色像素（选中态）===")
    sub = im[40:200, 0:75].astype(int)
    R, G, B = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    cyan = (G > 150) & (B > 150) & (R < 130)
    ys, xs = np.where(cyan)
    if len(ys):
        print(f"  青色像素 {len(ys)} 个")
        print(f"  y 范围 {ys.min()+40}..{ys.max()+40}  中心 {ys.mean()+40:.1f}")
        print(f"  x 范围 {xs.min()}..{xs.max()}")
    else:
        print("  未发现青色像素")

    print("\n=== 图标列 x=0..70 逐行亮像素（thr=110）→ 簇 ===")
    band = im[:, 0:70].mean(axis=2)
    spark = (band > 110).sum(axis=1) >= 2
    for a, b in runs_of(spark[:700]):
        print(f"  y={a:4d}..{b:4d}  高={b-a+1:3d}  中心={(a+b)/2:6.1f}")

    print("\n=== 同样的簇，但用青色掩码（只看选中态）===")
    cy_all = ((im[:, :, 1] > 150) & (im[:, :, 2] > 150)
              & (im[:, :, 0] < 130))
    spark2 = cy_all[:, 0:75].sum(axis=1) >= 2
    for a, b in runs_of(spark2[:700]):
        print(f"  y={a:4d}..{b:4d}  高={b-a+1:3d}  中心={(a+b)/2:6.1f}")


if __name__ == "__main__":
    main()
