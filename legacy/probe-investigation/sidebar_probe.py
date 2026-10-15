"""sidebar_probe.py — 定位侧栏图标位置与其对应的页面（只读，不点击）

目标：找出 1_ww.png 在侧栏的 y 位置，并列出所有侧栏图标候选，
      以便用户确认该图标通向哪个页面。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

from template_probe import capture_okww, OUT_DIR

SIDEBAR_W = 60      # 侧栏大致宽度


def main():
    hwnd, pid, title, r, fw, fh, frame = capture_okww()
    print("=" * 64)
    print("侧栏图标测绘（只读）")
    print("=" * 64)
    print(f"窗口 {fw}x{fh}")

    tpl = np.array(Image.open(r"E:\TOOLS\ScriptsGames\Onetap\templates\1_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape
    print(f"1_ww.png 尺寸 {tw}x{th}")

    # 1_ww 的已知匹配位置
    from template_probe import match_template
    res = match_template(frame, tpl)
    print(f"\n1_ww 匹配: score={res[0]:.4f} pos=({res[1]},{res[2]})  中心=({res[1]+tw//2},{res[2]+th//2})")

    # 扫描侧栏，找出所有「图标样」的纵向簇（亮像素）
    bar = frame[:, :SIDEBAR_W]
    g = bar.astype(np.float32).mean(axis=2)
    rowsum = (g > 110).sum(axis=1)          # 每行较亮像素数
    active = rowsum > 2

    print(f"\n侧栏竖向亮区簇（阈值>110，每行>2 像素）:")
    runs = []
    start = None
    for y, a in enumerate(active):
        if a and start is None:
            start = y
        elif not a and start is not None:
            if y - start >= 6:
                runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, len(active) - 1))

    for i, (y0, y1) in enumerate(runs):
        cy = (y0 + y1) // 2
        # 该行的水平范围
        cols = np.where((g[y0:y1 + 1] > 110).any(axis=0))[0]
        x0, x1 = (cols.min(), cols.max()) if len(cols) else (0, 0)
        mark = ""
        if abs(cy - (res[2] + th // 2)) <= 6:
            mark = "   <=== 1_ww 在这里"
        print(f"  [{i}] y={y0}..{y1}  中心y={cy}  x={x0}..{x1}{mark}")

    # 落盘侧栏放大图
    crop = frame[:, :SIDEBAR_W + 20]
    big = Image.fromarray(crop).resize(((SIDEBAR_W + 20) * 3, fh * 3), Image.NEAREST)
    out = OUT_DIR / "sidebar-zoom.png"
    big.save(out)
    print(f"\n[落盘] {out.name}  （侧栏放大 3x）")

    # 落盘 1_ww 匹配处的放大图
    mx, my = res[1], res[2]
    pad = 12
    c2 = frame[max(0, my - pad):my + th + pad, max(0, mx - pad):mx + tw + pad]
    big2 = Image.fromarray(c2).resize((c2.shape[1] * 6, c2.shape[0] * 6), Image.NEAREST)
    out2 = OUT_DIR / "icon1-zoom.png"
    big2.save(out2)
    print(f"[落盘] {out2.name}  （1_ww 匹配处放大 6x）")


if __name__ == "__main__":
    main()
