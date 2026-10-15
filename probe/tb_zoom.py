"""tb_zoom.py — 放大第5、第6个任务栏图标供指认（只读）"""

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
    y0, h = sh - 58, 56
    got = C.capture_region(1300, y0, 220, h)
    d, fw, fh = got
    img = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    big = Image.fromarray(img).resize((fw * 8, fh * 8), Image.LANCZOS)
    big.save(OUT / "tb-icon-5-6-8x.png")
    print(f"落盘 tb-icon-5-6-8x.png  区域 x=1300..1520 y={y0}..{y0+h} (8x)")

    # 每个图标单独巨大化
    for label, x in [("A_x1335", 1320), ("B_x1393", 1378), ("C_x1445", 1430)]:
        g2 = C.capture_region(x, y0, 50, h)
        d2, w2, h2 = g2
        a2 = np.frombuffer(d2, dtype=np.uint8).reshape(h2, w2, 4)[:, :, [2, 1, 0]]
        b2 = Image.fromarray(a2).resize((w2 * 10, h2 * 10), Image.LANCZOS)
        b2.save(OUT / f"tb-{label}.png")
        print(f"  落盘 tb-{label}.png  (x={x}..{x+50}, 10x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
