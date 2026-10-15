"""nte_sidebar.py — 展开侧边栏并勘察（ok-nte）

ok-nte 侧栏当前是收起的（只有图标）。点击顶部 ☰ 应可展开，露出文字标签。
目的：
  1. 找到并点击展开按钮
  2. 抓展开后的画面，确认「日常任务」等文字可见
  3. 为「文字锚点」采集做准备
"""

import sys
import time
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C
from nte_main import find_nte_layer2, R

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")

PUL = ctypes.POINTER(ctypes.c_ulong)


class MI(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("md", ctypes.c_ulong), ("fl", ctypes.c_ulong),
                ("t", ctypes.c_ulong), ("ex", PUL)]


class IN(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MI)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


def click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y)
    time.sleep(0.1)
    nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    for f in (0x0001 | 0x8000, 0x0002, 0x0004):
        i = IN(); i.type = 0
        i.mi.dx, i.mi.dy, i.mi.fl = nx, ny, f
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(IN))
        time.sleep(0.05)


def c2s(h, cx, cy):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P(cx, cy); user32.ClientToScreen(h, ctypes.byref(p))
    return p.x, p.y


def main():
    ws = [x for x in find_nte_layer2() if x[4] > 200 and x[6]]
    ws.sort(key=lambda x: -x[4] * x[5])
    hwnd = ws[0][0]
    user32.ShowWindow(hwnd, 9)
    time.sleep(0.4)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.r - r.l, r.b - r.t
    print(f"ok-nte hwnd={hwnd} {w}x{h} @({r.l},{r.t}) 前台={user32.GetForegroundWindow()==hwnd}")

    got = C.capture_region(r.l, r.t, w, h)
    d, fw, fh = got
    f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(f).save(OUT / "nte-sidebar-before.png")

    # ☰ 在左上角，约 (30, 78)（由整窗图目视）
    for label, (cx, cy) in [("☰(30,78)", (30, 78)), ("☰(32,80)", (32, 80))]:
        sx, sy = c2s(hwnd, cx, cy)
        print(f"\n点击 {label} -> 屏幕 ({sx},{sy})")
        click(sx, sy)
        time.sleep(1.4)
        r2 = R(); user32.GetWindowRect(hwnd, ctypes.byref(r2))
        w2, h2 = r2.r - r2.l, r2.b - r2.t
        got2 = C.capture_region(r2.l, r2.t, w2, h2)
        if not got2:
            continue
        d2, fw2, fh2 = got2
        f2 = np.frombuffer(d2, dtype=np.uint8).reshape(fh2, fw2, 4)[:, :, [2, 1, 0]]
        Image.fromarray(f2).save(OUT / f"nte-sidebar-{cx}_{cy}.png")

        # 侧栏宽度：看左侧 300px 内的亮像素分布
        bar = f2[:, :300].astype(np.float32).mean(axis=2)
        colsum = (bar > 110).sum(axis=0)
        nonzero = np.where(colsum > 0)[0]
        rightmost = nonzero.max() if len(nonzero) else 0
        print(f"   窗口 {fw2}x{fh2}  侧栏内容最右 x={rightmost}")
        print(f"   落盘 nte-sidebar-{cx}_{cy}.png")

        # 侧栏区域裁图放大
        crop = f2[:, :min(300, fw2)]
        Image.fromarray(crop).save(OUT / f"nte-sidebar-crop-{cx}.png")

        if rightmost > 120:
            print("   => 侧栏似乎已展开（内容超出图标宽度）")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
