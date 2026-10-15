"""taskbar_apps2.py — 正确定位任务栏"应用按钮"区（只读）

任务栏布局（从左到右）：
  [开始/搜索/任务视图] ... [应用按钮区] ... [系统托盘: ^ 中 拼 音量 时间]

应用按钮区在屏幕中部偏右。上一次误取了系统托盘。
本次扫描整条任务栏，用"彩色度"（饱和度）识别应用图标 ——
应用图标多为彩色，而系统托盘图标多为单色。
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
    sw, sh = C.user32.GetSystemMetrics(0), C.user32.GetSystemMetrics(1)
    y0, h = sh - 56, 52
    got = C.capture_region(0, y0, sw, h)
    d, fw, fh = got
    img = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(img).save(OUT / "tb-all.png")

    f = img.astype(np.float32)
    g = f.mean(axis=2)
    # 饱和度：max-min
    sat = f.max(axis=2) - f.min(axis=2)

    # 应用图标：有颜色 或 足够亮
    active = (sat > 35) | (g > 110)
    colactive = active.sum(axis=0) > 2

    runs = []
    s = None
    for i, v in enumerate(colactive):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= 12:
                runs.append((s, i - 1))
            s = None
    if s is not None:
        runs.append((s, len(colactive) - 1))

    print(f"屏幕 {sw}x{sh}   任务栏 y={y0}..{y0+h}")
    print(f"检出 {len(runs)} 个候选簇（宽>=12）:\n")
    print(f"{'序':>3} {'屏幕x范围':>18} {'中心x':>7} {'宽':>5}  平均饱和度")
    for i, (a, b) in enumerate(runs):
        s_ = sat[:, a:b + 1].mean()
        print(f"{i:>3} {f'{a}..{b}':>18} {(a+b)//2:>7} {b-a:>5}  {s_:.1f}")

    big = Image.fromarray(img[:, :]).resize((fw * 2, fh * 2), Image.LANCZOS)
    big.save(OUT / "tb-all-2x.png")

    # 只裁中部（排除最左的开始按钮和最右托盘）
    mid = img[:, 1000:2200]
    bm = Image.fromarray(mid).resize((mid.shape[1] * 2, mid.shape[0] * 2), Image.LANCZOS)
    bm.save(OUT / "tb-mid-2x.png")
    print(f"\n落盘 tb-all-2x.png / tb-mid-2x.png（中部 x=1000..2200）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
