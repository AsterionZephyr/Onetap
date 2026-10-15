# -*- coding: utf-8 -*-
"""探测：ok-nte 侧栏结构。

目的：ok-ww 用 match.find_sidebar_item(frame, index=2) 定位「任务」项。
ok-nte 的任务页在侧栏第几项？本脚本把整条侧栏枚举出来与人眼读数比对。

用法：
    python -X utf8 probe/_probe_nte_sidebar.py [帧路径]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from orchestrator import match

FRAME = sys.argv[1] if len(sys.argv) > 1 else r"logs\shots\nte-page-00.png"


def main():
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    h, w = im.shape[:2]
    print(f"帧 {w} x {h}  ({FRAME})")

    print("\n=== match 模块的侧栏常量 ===")
    for name in ("SIDEBAR_TEXT_X0", "SIDEBAR_TEXT_X1", "SIDEBAR_TEXT_THR",
                 "SIDEBAR_MIN_PIX", "SIDEBAR_GAP", "SIDEBAR_MIN_ITEMS",
                 "SIDEBAR_SCAN_H_FRAC", "SIDEBAR_PITCH_TOL", "SIDEBAR_ITEM_TASKS"):
        print(f"  {name} = {getattr(match, name, '(无)')}")

    print("\n=== find_sidebar_item 逐 index ===")
    for i in range(16):
        r = match.find_sidebar_item(im, i)
        if r is None:
            print(f"  [{i}] None —— 停")
            break
        items = r.get("items", [])
        pos = r.get("pos")
        pitch = r.get("pitch")
        print(f"  [{i}] pos={pos}  pitch={pitch:.2f}  项数={len(items)}")

    print("\n=== 一次性看全部项（index=0 的 items）===")
    r = match.find_sidebar_item(im, 0)
    if r:
        for j, it in enumerate(r.get("items", [])):
            print(f"  项[{j}] {it}")


if __name__ == "__main__":
    main()
