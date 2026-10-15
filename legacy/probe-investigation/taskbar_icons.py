"""taskbar_icons.py — 精确切分任务栏应用按钮并标号（只读）"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")


def main():
    sw, sh = C.user32.GetSystemMetrics(0), C.user32.GetSystemMetrics(1)
    # 应用按钮区：从亮度看集中在 x≈2150..2560（右侧）
    x0, y0, w, h = 2100, sh - 56, 460, 52
    got = C.capture_region(x0, y0, w, h)
    d, fw, fh = got
    img = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(img).save(OUT / "tb-apps.png")

    g = img.astype(np.float32).mean(axis=2)
    # 找图标簇：列方向上有明显亮度的连续段
    colmax = g.max(axis=0)
    active = colmax > 90
    runs = []
    s = None
    for i, v in enumerate(active):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= 6:
                runs.append((s, i - 1))
            s = None
    if s is not None:
        runs.append((s, len(active) - 1))

    print(f"应用按钮区 x={x0}..{x0+w}  y={y0}..{y0+h}")
    print(f"检出 {len(runs)} 个图标簇：\n")
    print(f"{'序':>3} {'屏幕x范围':>18} {'中心x':>7} {'中心y':>7}  宽")
    for i, (a, b) in enumerate(runs):
        sa, sb = x0 + a, x0 + b
        cx, cy = (sa + sb) // 2, y0 + h // 2
        print(f"{i:>3} {f'{sa}..{sb}':>18} {cx:>7} {cy:>7}  {sb-sa}")

    # 落盘放大图（4x）
    big = Image.fromarray(img).resize((fw * 4, fh * 4), Image.LANCZOS)
    big.save(OUT / "tb-apps-4x.png")
    print(f"\n落盘 tb-apps.png / tb-apps-4x.png")

    # 单独把每个簇裁出来拼一张
    if runs:
        tiles = []
        for a, b in runs:
            t = img[:, max(0, a - 4):min(fw, b + 4)]
            tiles.append(t)
        mh = max(t.shape[0] for t in tiles)
        pad = 10
        totw = sum(t.shape[1] + pad for t in tiles) + pad
        canvas = np.full((mh + 2 * pad, totw, 3), 60, dtype=np.uint8)
        x = pad
        for t in tiles:
            canvas[pad:pad + t.shape[0], x:x + t.shape[1]] = t
            x += t.shape[1] + pad
        b2 = Image.fromarray(canvas).resize((canvas.shape[1] * 4, canvas.shape[0] * 4),
                                            Image.LANCZOS)
        b2.save(OUT / "tb-tiles.png")
        print(f"落盘 tb-tiles.png（各图标单独裁出，左→右按序号）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
