"""nte_enter.py — 点击「启动应用」进入 ok-nte 主界面（单次点击 + 前后验证）

只点一次启动器上的「▶ 启动应用」按钮（绿色），然后观察是否出现主界面。
安全措施与 ok-ww 一致：点击前记录状态、验证前台与遮挡、点击后抓图对比。
"""

import sys
import time
import subprocess
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template

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


def top_at(x, y):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    return user32.GetAncestor(user32.WindowFromPoint(P(x, y)), 2)


def nte_win():
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            t = b.value
            if t.lower() == "ok-nte":
                c = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(h, c, 128)
                res.append((h, c.value, t))
        return True

    user32.EnumWindows(cb, 0)
    return res


class R(ctypes.Structure):
    _fields_ = [("l", wt.LONG), ("t", wt.LONG), ("r", wt.LONG), ("b", wt.LONG)]


def main():
    print("=" * 72)
    print("进入 ok-nte 主界面：点击「▶ 启动应用」")
    print("=" * 72)

    ws = nte_win()
    if not ws:
        print("[NG] 未找到 ok-nte 窗口")
        return 1
    hwnd, cls, title = ws[0]
    user32.ShowWindow(hwnd, 9)
    time.sleep(0.4)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.r - r.l, r.b - r.t
    fg_ok = user32.GetForegroundWindow() == hwnd
    print(f"hwnd={hwnd} class={cls} {w}x{h} @({r.l},{r.t})  前台={fg_ok}")
    if not fg_ok:
        print("[NG] 置前台失败")
        return 1

    got = C.capture_region(r.l, r.t, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(frame).save(OUT / "nte-before.png")
    print(f"帧 {fw}x{fh}  INV-1 {'OK' if (fw,fh)==(w,h) else 'NG'}")

    # 定位绿色「启动应用」按钮：找绿色像素块
    f = frame.astype(np.float32)
    R_, G_, B_ = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    green = (G_ > 140) & (G_ - R_ > 40) & (G_ - B_ > 30)
    cols = np.where(green.sum(axis=0) > 8)[0]
    rows = np.where(green.sum(axis=1) > 8)[0]
    if not len(cols) or not len(rows):
        print("[NG] 未找到绿色按钮")
        return 1
    print(f"绿色区域 x={cols.min()}..{cols.max()}  y={rows.min()}..{rows.max()}")
    bx0, bx1 = cols.min(), cols.max()
    by0, by1 = rows.min(), rows.max()
    bcx, bcy = (bx0 + bx1) // 2, (by0 + by1) // 2
    print(f"按钮中心 窗口内=({bcx},{bcy})  尺寸 {bx1-bx0}x{by1-by0}")

    # 裁图确认
    crop = frame[max(0, by0 - 12):by1 + 12, max(0, bx0 - 12):bx1 + 12]
    Image.fromarray(crop).save(OUT / "nte-startbtn.png")
    print("落盘 nte-startbtn.png")

    sx, sy = c2s(hwnd, bcx, bcy)
    topw = top_at(sx, sy)
    print(f"屏幕坐标=({sx},{sy})  顶层 hwnd={topw}  是ok-nte={topw == hwnd}")
    if topw != hwnd:
        print("[NG] 被遮挡，中止")
        return 1

    print(f"\n[点击] ({sx},{sy})")
    click(sx, sy)
    time.sleep(2.5)

    # 观察结果
    print("\n[点击后]")
    for i in range(12):
        p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ok-nte.exe",
                            "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, errors="replace").stdout
        pids = [l.split('","')[1] for l in p.splitlines() if l.startswith('"')]
        ws2 = nte_win()
        info = []
        for h2, c2, t2 in ws2:
            r2 = R(); user32.GetWindowRect(h2, ctypes.byref(r2))
            info.append((h2, (r2.r - r2.l, r2.b - r2.t), c2, t2))
        print(f"  [{i*2}s] ok-nte={pids} 窗口={info}")
        if i == 0:
            got2 = C.capture_region(96, 96, 1393, 1047)
            if got2:
                d2, w2, h2_ = got2
                f2 = np.frombuffer(d2, dtype=np.uint8).reshape(h2_, w2, 4)[:, :, [2, 1, 0]]
                Image.fromarray(f2).save(OUT / "nte-after.png")
        time.sleep(2)
    print("落盘 nte-after.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
