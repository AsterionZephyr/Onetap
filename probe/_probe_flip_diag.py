# -*- coding: utf-8 -*-
r"""诊断 N-1：上下翻转的帧里，find_menu_glyph 到底匹配到了什么。

用法：
    & "D:\WORKs\Anaconda\python.exe" -X utf8 probe\_probe_flip_diag.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import match  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "probe", "running-000.png")


def load(path):
    return np.asarray(Image.open(path).convert("RGB"))


def dump_bars(rgb, tag):
    """复刻 find_menu_glyph 的行扫描，打印左上窄条内的所有候选线。"""
    h, w = rgb.shape[:2]
    x1 = min(w, match.MENU_SCAN_W)
    y1 = min(h, match.MENU_SCAN_H)
    g = match.to_gray(rgb[:y1, :x1])
    bright = g > match.MENU_BRIGHT

    bars = []
    for y in range(y1):
        xs = np.where(bright[y])[0]
        if len(xs) < match.MENU_MIN_ROW_PIX:
            continue
        splits = np.where(np.diff(xs) > 1)[0]
        runs = np.split(xs, splits + 1)
        run = max(runs, key=len)
        if len(run) < match.MENU_MIN_ROW_PIX:
            continue
        bars.append((y, int(run[0]), int(run[-1])))

    groups = []
    cur = [bars[0]]
    for b in bars[1:]:
        if b[0] - cur[-1][0] <= 1:
            cur.append(b)
        else:
            groups.append(cur)
            cur = [b]
    groups.append(cur)

    geom = []
    for gp in groups:
        _, bx0, bx1 = max(gp, key=lambda t: t[2] - t[1])
        cy = sum(t[0] for t in gp) / len(gp)
        geom.append((cy, bx0, bx1))
    geom.sort(key=lambda t: t[0])

    print(f"\n=== {tag}  frame {w}x{h}  扫描区 {x1}x{y1}  合并后 {len(geom)} 条线 ===")
    for cy, b0, b1 in geom:
        print(f"   cy={cy:6.1f}  x={b0:3d}..{b1:3d}  len={b1-b0+1:3d}")
    return geom


def main():
    rgb = load(SRC)
    h, w = rgb.shape[:2]
    flipped = np.ascontiguousarray(rgb[::-1])

    print("原文（期望 ☰ 在 y=73..86 附近、x=21..39）")
    glyph = match.find_menu_glyph(rgb)
    print(f"  find_menu_glyph -> {glyph}")

    dump_bars(rgb, "原帧")

    print("\n" + "-" * 70)
    print("上下翻转（☰ 被翻到 y≈1164..1177，左上角**不应**再有 ☰）")
    glyph_f = match.find_menu_glyph(flipped)
    print(f"  find_menu_glyph -> {glyph_f}")

    geom = dump_bars(flipped, "翻转帧")

    # 把命中区域放大存盘，人眼确认那是什么
    if glyph_f is not None:
        px, py = glyph_f["pos"]
        print(f"\n  命中 pos={glyph_f['pos']} bbox={glyph_f['bbox']} "
              f"centers={glyph_f['centers']} gaps={glyph_f['gaps']}")
        y0 = max(0, py - 40)
        y1 = min(h, py + 60)
        crop = flipped[y0:y1, 0:min(w, 160)]
        out = os.path.join(ROOT, "logs", "shots", "flip-hit-zoom.png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im = Image.fromarray(crop)
        im = im.resize((im.width * 4, im.height * 4), Image.NEAREST)
        im.save(out)
        print(f"  [落盘] {out}  (crop y={y0}..{y1}, 放大 4x)")
        print(f"  命中行的灰度最大值 = {match.to_gray(flipped[y0:y1, 0:160]).max():.0f}")


if __name__ == "__main__":
    main()
