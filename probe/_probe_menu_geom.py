# -*- coding: utf-8 -*-
"""量取真 ☰ 与干扰项的几何分布，为阈值提供依据（不要凭感觉设常数）。

正样本：4 张真 ok-ww 帧（三种尺寸）。
负样本：上下翻转帧 + DSH 终端帧 + GUI 截图。

输出每组候选的 (x0, x1, len, cy, gap)，以及真 ☰ 的「左边缘占窗口宽比例」。

用法：
    & "D:\WORKs\Anaconda\python.exe" -X utf8 probe\_probe_menu_geom.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import match  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "logs", "shots")

POS = [
    ("ok-ww 1875x1250", os.path.join(ROOT, "probe", "running-000.png")),
    ("ok-ww 1822x1000", os.path.join(ROOT, "probe", "obs-000.png")),
    ("ok-ww 1500x1000", os.path.join(ROOT, "probe", "okww-now.png")),
    ("ok-ww 1458x800", os.path.join(S, "bg-verify-002.png")),
]
NEG = [
    ("DSH 终端 003", os.path.join(S, "003-task-loop-start.png")),
    ("GUI gui-now", os.path.join(S, "gui-now.png")),
]


def load(p):
    return np.asarray(Image.open(p).convert("RGB"))


def bars_of(rgb):
    """复刻 find_menu_glyph 的行扫描与合并，返回 geom 列表。"""
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
    if not bars:
        return []
    groups, cur = [], [bars[0]]
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
    return geom


def main():
    print("=" * 78)
    print("真 ☰ 的几何（每一组三线都要看：x0 是否贴近左边缘、len、gap）")
    print("=" * 78)
    for tag, path in POS:
        if not os.path.isfile(path):
            print(f"\n[{tag}] 缺文件 {path}")
            continue
        rgb = load(path)
        h, w = rgb.shape[:2]
        geom = bars_of(rgb)
        g = match.find_menu_glyph(rgb)
        print(f"\n[{tag}] {w}x{h}  候选线 {len(geom)} 条")
        for cy, b0, b1 in geom:
            mark = ""
            if g is not None and abs(cy - g["centers"][0]) < 0.6:
                mark = "  <== 命中首线"
            print(f"    cy={cy:6.1f} x={b0:3d}..{b1:3d} len={b1-b0+1:3d}{mark}")
        if g is not None:
            x0 = g["bbox"][0]
            print(f"    命中 pos={g['pos']} len={g['line_len']} "
                  f"gaps={g['gaps']} x0/w={x0}/{w}={x0/w:.4f} "
                  f"x1/w={g['bbox'][2]}/{w}={g['bbox'][2]/w:.4f}")

    print("\n" + "=" * 78)
    print("干扰项：真实抓帧里的非 ☰ 三线组（★ = 会被当前实现误收的那些）")
    print("=" * 78)
    for tag, path in NEG:
        if not os.path.isfile(path):
            print(f"\n[{tag}] 缺文件 {path}")
            continue
        rgb = load(path)
        h, w = rgb.shape[:2]
        geom = bars_of(rgb)
        g = match.find_menu_glyph(rgb)
        print(f"\n[{tag}] {w}x{h}  候选线 {len(geom)} 条  "
              f"find_menu_glyph={'命中 ' + str(g['pos']) if g else '否决'}")
        if g:
            print(f"    ★ 命中 len={g['line_len']} gaps={g['gaps']} "
                  f"x0/w={g['bbox'][0]/w:.4f}")

    print("\n" + "=" * 78)
    print("翻转帧（N-1 负向对照）：☰ 被翻走，左上角只剩干扰项")
    print("=" * 78)
    rgb = load(POS[0][1])
    h, w = rgb.shape[:2]
    flipped = np.ascontiguousarray(rgb[::-1])
    geom = bars_of(flipped)
    g = match.find_menu_glyph(flipped)
    print(f"翻转帧 {w}x{h}  候选线 {len(geom)} 条  "
          f"find_menu_glyph={'命中 ' + str(g['pos']) if g else '否决'}")
    for cy, b0, b1 in geom:
        print(f"    cy={cy:6.1f} x={b0:3d}..{b1:3d} len={b1-b0+1:3d}")
    if g:
        print(f"    ★ 命中 len={g['line_len']} gaps={g['gaps']} "
              f"x0/w={g['bbox'][0]/w:.4f} x1/w={g['bbox'][2]/w:.4f}")


if __name__ == "__main__":
    main()
