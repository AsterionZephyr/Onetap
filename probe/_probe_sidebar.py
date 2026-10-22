# -*- coding: utf-8 -*-
r"""量取 ok-ww 侧栏「任务」项的位置，为导航点击提供**不依赖截图模板**的定位。

背景（FAULT #11）：
    step8_run_task.py:117-123 的导航点击目标来自
        ident = match.verify_identity(frame.rgb, tpl)
        cx = ident["pos"][0] + tw // 2 ; cy = ident["pos"][1] + th // 2
    即「身份锚点的 pos + 模板半宽高」。
    改造前 verify_identity 返回的是**侧栏「任务」图标**位置（1_ww.png 匹配），
    改造后返回的是**☰ 菜单图标**位置 ⇒ 导航点到了 ☰，页面永远停在原处。

正确做法（FRAMEWORK.md §3.7）：导航目标应**程序化定位**，不依赖截图模板。
侧栏项是「图标 + 文字」，垂直排列、行距随窗口高度缩放 ⇒ 用**内容簇序号**
（0-based）而非硬编码绝对 y。

本脚本量取：侧栏各菜单项的文字行 y 中心、行距、以及「任务」是第几项。

用法：
    & "D:\WORKs\Anaconda\python.exe" -X utf8 probe\_probe_sidebar.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import match  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "logs", "runs", "run-20261015-191549", "shots")

FRAMES = [
    ("about 页 1458x800", os.path.join(D, "002-task-loop-start.png")),
]


def load(p):
    return np.asarray(Image.open(p).convert("RGB"))


def row_profile(rgb, x0, x1, y0, y1, thr=110):
    """返回 [y, 该行亮像素数] 的列表。"""
    g = match.to_gray(rgb[y0:y1, x0:x1])
    return [(y0 + i, int((g[i] > thr).sum())) for i in range(g.shape[0])]


def clusters(prof, min_pix=1, gap=3):
    """把有亮像素的相邻行合并成簇，返回 (y_start, y_end, peak_y, total)。"""
    on = [(y, c) for y, c in prof if c >= min_pix]
    if not on:
        return []
    out, cur = [], [on[0]]
    for item in on[1:]:
        if item[0] - cur[-1][0] <= gap:
            cur.append(item)
        else:
            out.append(cur)
            cur = [item]
    out.append(cur)
    res = []
    for gp in out:
        ys = [y for y, _ in gp]
        cs = [c for _, c in gp]
        peak = ys[int(np.argmax(cs))]
        res.append((ys[0], ys[-1], peak, sum(cs)))
    return res


def main():
    for tag, path in FRAMES:
        if not os.path.isfile(path):
            print(f"[缺文件] {path}")
            continue
        rgb = load(path)
        h, w = rgb.shape[:2]
        print("=" * 74)
        print(f"{tag}   {w}x{h}")
        print("=" * 74)

        # 侧栏文字带：☰ 在 x=17..31，侧栏图标/文字大约在 x=10..90
        print("\n[侧栏 x=8..95 的文字行簇]（y 从 0 起，全高扫描）")
        prof = row_profile(rgb, 8, 95, 0, h, thr=110)
        cl = clusters(prof, min_pix=2, gap=2)
        for (y0, y1, peak, tot) in cl:
            print(f"   y={y0:4d}..{y1:4d}  peak={peak:4d}  亮像素合计={tot:5d}")

        print(f"\n[共 {len(cl)} 个文字行簇]")

        # 报告行距
        if len(cl) >= 2:
            peaks = [p for _, _, p, _ in cl]
            gaps = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
            print(f"   相邻簇 peak 间距 = {gaps}")
            print(f"   中位间距 = {int(np.median(gaps))}")


if __name__ == "__main__":
    main()
