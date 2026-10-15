"""verify_top.py — 核对当前页顶端内容（只读）

用户称"每日任务行在本页最顶端"。
本脚本把 ok-ww 顶部 300px 单独裁出并放大，供肉眼核对，
同时打印该区域的亮度分布，确认是否真的有内容。
"""

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
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    fg = C.user32.GetForegroundWindow()
    print(f"ok-ww hwnd={hwnd} rect=({r.left},{r.top})-({r.right},{r.bottom}) {w}x{h}")
    print(f"前台={fg}  ok-ww在前台={fg == hwnd}")

    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        print("[NG] 抓帧失败")
        return 1
    d, fw, fh = got
    f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

    Image.fromarray(f).save(OUT / "top-full.png")
    print(f"整窗落盘 top-full.png  {fw}x{fh}")

    # 顶部 320px
    top = f[0:320, :]
    Image.fromarray(top).save(OUT / "top-320.png")
    print(f"顶部 320px 落盘 top-320.png")

    # 顶部 320px 放大 2x
    b = Image.fromarray(top).resize((top.shape[1] * 2, top.shape[0] * 2), Image.LANCZOS)
    b.save(OUT / "top-320-2x.png")
    print(f"放大落盘 top-320-2x.png")

    # 逐行亮度，看前 320 行哪里是空、哪里有内容
    g = f[0:320].astype(np.float32).mean(axis=2)
    print("\n顶部各行内容量（每 20 行汇总，>60 的像素数）:")
    for y in range(0, 320, 20):
        band = g[y:y + 20]
        n = int((band > 60).sum())
        bar = "#" * min(60, n // 200)
        print(f"  y={y:3d}-{y+19:3d}  {n:6d}  {bar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
