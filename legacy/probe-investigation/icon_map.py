"""icon_map.py — 逐个侧栏图标的精确裁图（只读，不点击）

目的：把侧栏每个图标单独裁出来放大落盘，供用户指认
      "书架样式" 的是哪一个。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C
import ctypes

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")

# 由 sidebar_probe 得到的侧栏图标竖直簇
CLUSTERS = [
    (120, 139), (172, 189), (220, 239), (270, 289), (320, 339),
    (370, 389), (420, 439), (470, 488), (523, 536),
    (860, 873), (910, 929), (960, 979),
]


def main():
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    fg = C.user32.GetForegroundWindow()
    print(f"ok-ww {w}x{h} @ ({r.left},{r.top})   前台={fg == hwnd}")
    if fg != hwnd:
        print("[!!] 不在前台，抓到的可能不是 ok-ww，结果不可信")

    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        print("[NG] 抓帧失败")
        return 1
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(frame).save(OUT / "iconmap-source.png")

    # 每个图标单独裁出，横向取 0..60，纵向上下各留 6px
    tiles = []
    for i, (y0, y1) in enumerate(CLUSTERS):
        cy0, cy1 = max(0, y0 - 8), min(fh, y1 + 8)
        crop = frame[cy0:cy1, 0:56]
        tiles.append((i, cy0, cy1, crop))

    # 拼成一张对比图（横向排列，放大 4x）
    maxh = max(t[3].shape[0] for t in tiles)
    pad = 14
    total_w = sum(t[3].shape[1] + pad for t in tiles) + pad
    canvas = np.full((maxh + 2 * pad, total_w, 3), 40, dtype=np.uint8)
    x = pad
    for i, cy0, cy1, crop in tiles:
        ch, cw, _ = crop.shape
        canvas[pad:pad + ch, x:x + cw] = crop
        x += cw + pad

    big = Image.fromarray(canvas).resize(
        (canvas.shape[1] * 4, canvas.shape[0] * 4), Image.NEAREST)
    out = OUT / "icons-strip.png"
    big.save(out)
    print(f"\n落盘 {out}   顺序（左→右）:")
    for i, cy0, cy1, _ in tiles:
        print(f"  [{i}] y={cy0}..{cy1}  中心y={(cy0+cy1)//2}")

    # 单独再放大 "第4个"（索引3，y=270..289）
    print("\n单独放大【第 4 个图标】(y=270..289):")
    c = frame[262:297, 0:56]
    b2 = Image.fromarray(c).resize((c.shape[1] * 10, c.shape[0] * 10), Image.NEAREST)
    out2 = OUT / "icon-4th.png"
    b2.save(out2)
    print(f"  落盘 {out2}")

    # 也放大 1_ww 所在的那个（索引2）
    c3 = frame[212:247, 0:56]
    b3 = Image.fromarray(c3).resize((c3.shape[1] * 10, c3.shape[0] * 10), Image.NEAREST)
    out3 = OUT / "icon-3rd.png"
    b3.save(out3)
    print(f"  落盘 {out3}（1_ww 所在，索引2）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
