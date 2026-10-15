"""page_map.py — 建立侧栏导航地图（点击每个图标并记录落到的页面）

目的：确认「1_ww.png」（书架/任务图标，y≈230）通往哪一页，
      并确认该页顶端就是「每日任务 … 开始」。

只点侧栏图标（纯导航，无副作用），每点一次抓图落盘。
"""

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")

user32 = C.user32
PUL = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


def click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y)
    time.sleep(0.08)
    nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    for f in (0x0001 | 0x8000, 0x0002, 0x0004):
        i = INPUT(); i.type = 0
        i.mi.dx, i.mi.dy, i.mi.dwFlags = nx, ny, f
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
        time.sleep(0.04)


def c2s(hwnd, cx, cy):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P(cx, cy); user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def grab(hwnd, r):
    w, h = r.right - r.left, r.bottom - r.top
    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        return None
    d, fw, fh = got
    return np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]


def main():
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 无 ok-ww")
        return 1
    hwnd, pid, title = wins[0]
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    print(f"ok-ww hwnd={hwnd} pid={pid}  前台={user32.GetForegroundWindow()==hwnd}")

    r = C.get_window_rect(hwnd)
    frame = grab(hwnd, r)
    t1 = np.array(Image.open(TPL / "1_ww.png").convert("RGB"))
    sc, mx, my = match_template(frame, t1)
    print(f"1_ww 定位 score={sc:.4f} pos=({mx},{my})")
    if sc < 0.95:
        print("[NG] 侧栏图标定位失败")
        return 1
    th, tw, _ = t1.shape
    tcx, tcy = mx + tw // 2, my + th // 2
    sx, sy = c2s(hwnd, tcx, tcy)
    print(f"1_ww 中心 窗口内=({tcx},{tcy})  屏幕=({sx},{sy})")

    # 顶部区域（用于判断页面）
    print("\n[点击 1_ww]")
    click(sx, sy)
    time.sleep(1.5)

    r2 = C.get_window_rect(hwnd)
    f2 = grab(hwnd, r2)
    Image.fromarray(f2).save(OUT / "page-after-nav.png")
    print(f"  已抓图 page-after-nav.png  {f2.shape[1]}x{f2.shape[0]}")

    # 在导航后的页面里查 2_ww 文字段
    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    sub = tpl[:, 9:9 + 98]
    sc2, mx2, my2 = match_template(f2, sub)
    print(f"  2_ww 文字段 score={sc2:.4f} pos=({mx2},{my2})")

    # 顶部 260px 裁图
    Image.fromarray(f2[:260]).save(OUT / "page-top.png")
    print(f"  落盘 page-top.png（顶部 260px）")

    if sc2 > 0.95:
        print(f"\n=> [OK] 该页顶端就是「每日任务」行（y={my2}）")
    else:
        print(f"\n=> 该页顶端不是「每日任务」行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
