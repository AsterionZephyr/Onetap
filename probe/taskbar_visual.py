"""taskbar_visual.py — 视觉定位任务栏上 ok-ww 的图标（只读）

任务栏按钮无独立 HWND（DirectUI 绘制），故改用视觉：
  1. 抓任务栏区域 (MSTaskListWClass 的 rect 及其周边)
  2. 放大落盘，供用户指认
  3. 用 ok-ww 的窗口图标模板匹配
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


def grab(x, y, w, h):
    got = C.capture_region(x, y, w, h)
    if got is None:
        return None
    d, fw, fh = got
    return np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]


def main():
    sw, sh = C.user32.GetSystemMetrics(0), C.user32.GetSystemMetrics(1)
    print(f"屏幕 {sw}x{sh}")

    # 任务栏整条
    tb = grab(0, sh - 60, sw, 60)
    Image.fromarray(tb).save(OUT / "taskbar-full.png")
    print(f"落盘 taskbar-full.png {tb.shape[1]}x{tb.shape[0]}")

    # 右侧 1/3 区域放大（应用按钮通常在这里，从右往左）
    x0 = int(sw * 0.60)
    seg = grab(x0, sh - 60, sw - x0, 60)
    Image.fromarray(seg).save(OUT / "taskbar-right.png")
    big = Image.fromarray(seg).resize((seg.shape[1] * 3, seg.shape[0] * 3), Image.LANCZOS)
    big.save(OUT / "taskbar-right-3x.png")
    print(f"落盘 taskbar-right.png / taskbar-right-3x.png  "
          f"区域 x={x0}..{sw}  ({seg.shape[1]}x{seg.shape[0]})")

    # 整条放大 2x
    b2 = Image.fromarray(tb).resize((tb.shape[1] * 2, tb.shape[0] * 2), Image.LANCZOS)
    b2.save(OUT / "taskbar-2x.png")

    # 打印任务栏各行亮度，看按钮分布
    g = tb.astype(np.float32).mean(axis=2)
    colmean = g.mean(axis=0)
    print("\n任务栏横向亮度（每 64px 汇总，找按钮簇）:")
    for x in range(0, sw, 64):
        v = colmean[x:x + 64].mean()
        bar = "#" * int(v / 4)
        print(f"  x={x:4d}  均值={v:6.1f}  {bar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
