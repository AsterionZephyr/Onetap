"""nte_reanchor.py — 程序化采集一个可靠的 ok-nte 身份锚点

教训：手工按坐标裁剪已连续失败 3 次（↔ 记错位置）。
本脚本改为**程序化定位**：
  1. 在左上角区域寻找"三条水平横线"的图案（☰ 汉堡菜单）
  2. 精确裁剪并保存
  3. 验证在多个页面/多个尺寸下都唯一且高分

☰ 的特征：3 条约等长的水平亮线，垂直间距均匀。
"""

import ctypes
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

from orchestrator import find_layer2, grab, force_foreground
from nte_main import all_hits
from template_probe import match_template

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")


def find_hamburger(frame, x0=0, x1=70, y0=0, y1=200):
    """在指定区域内找 ☰（三条水平亮线）。返回 (x0,y0,x1,y1) 或 None。"""
    sub = frame[y0:y1, x0:x1]
    g = sub.astype(np.float32).mean(axis=2)
    bright = g > 120
    rowsum = bright.sum(axis=1)
    # 找水平亮线：该行亮像素数 >= 8
    lines = [i for i, v in enumerate(rowsum) if v >= 8]
    if len(lines) < 3:
        return None
    # 聚类成线
    groups = []
    s = prev = lines[0]
    for i in lines[1:]:
        if i - prev > 2:
            groups.append((s, prev))
            s = i
        prev = i
    groups.append((s, prev))
    if len(groups) < 3:
        return None
    # 取相邻间距均匀的三条
    for i in range(len(groups) - 2):
        a, b, c = groups[i], groups[i + 1], groups[i + 2]
        ga = b[0] - a[1]
        gb = c[0] - b[1]
        if abs(ga - gb) <= 2 and 2 <= ga <= 10:
            ya, yc = a[0], c[1]
            # 横向范围取这三条线的并集
            band = bright[ya:yc + 1]
            cols = np.where(band.any(axis=0))[0]
            if len(cols) < 6:
                continue
            return (x0 + int(cols.min()), y0 + ya,
                    x0 + int(cols.max()), y0 + yc)
    return None


def main():
    ws = find_layer2("ok-nte")
    if not ws:
        print("[NG] 无 ok-nte 第二层窗口")
        return 1
    h = ws[0][0]
    force_foreground(h)
    f, r, fw, fh = grab(h)
    print(f"帧 {fw}x{fh}")

    box = find_hamburger(f)
    if not box:
        print("[NG] 未找到 ☰ 图案")
        # 落盘左上角供人工查看
        Image.fromarray(f[0:200, 0:80]).resize((80 * 6, 200 * 6), Image.NEAREST).save(
            OUT / "nte-hamburger-fail.png")
        print("  落盘 nte-hamburger-fail.png")
        return 1

    bx0, by0, bx1, by1 = box
    print(f"☰ 定位: x={bx0}..{bx1}  y={by0}..{by1}  ({bx1-bx0+1}x{by1-by0+1})")

    # 加边距，便于匹配时更稳定
    pad = 3
    ax0, ay0 = max(0, bx0 - pad), max(0, by0 - pad)
    ax1, ay1 = min(fw, bx1 + pad + 1), min(fh, by1 + pad + 1)
    anchor = f[ay0:ay1, ax0:ax1]
    Image.fromarray(anchor).save(TPL / "4_nte_menu.png")
    print(f"已保存 templates/4_nte_menu.png  {anchor.shape[1]}x{anchor.shape[0]}")

    # 唯一性验证
    hits = all_hits(f, anchor, 0.90, min_dist=20)
    print(f"唯一性: >=0.90 候选 = {len(hits)}")
    for i, (y, x, s) in enumerate(hits):
        print(f"  [{i}] {s:.4f} @({x},{y})")

    # 自匹配确认
    s, x, y = match_template(f, anchor)
    print(f"自匹配 score={s:.4f} @({x},{y})  期望 @({ax0},{ay0})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
