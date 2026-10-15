"""nte_sweep.py — 逐页勘察 ok-nte：点每个侧栏图标并记录该页内容

目的：找到 2_nte.png（「▶ 开始」按钮）所在的页面。
方法：对每个侧栏图标位置，点击后抓图并尝试匹配 2_nte.png。
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
from template_probe import match_template
from nte_main import find_nte_layer2, all_hits, R

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")

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
    # 侧栏图标 y 位置（由 1_nte.png 的两个命中 + 目视估计）
    # 先用图像法找侧栏所有图标簇
    ws = [x for x in find_nte_layer2() if x[4] > 200 and x[6]]
    if not ws:
        print("[NG] 无 ok-nte 主窗口")
        return 1
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
    f0 = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

    # 找侧栏图标簇（x<60）
    bar = f0[:, :60].astype(np.float32).mean(axis=2)
    rowsum = (bar > 110).sum(axis=1)
    active = rowsum > 2
    runs = []
    s = None
    for y, a in enumerate(active):
        if a and s is None:
            s = y
        elif not a and s is not None:
            if y - s >= 8:
                runs.append((s, y - 1))
            s = None
    if s is not None:
        runs.append((s, len(active) - 1))
    print(f"\n侧栏图标簇 {len(runs)} 个：")
    for i, (y0, y1) in enumerate(runs):
        print(f"  [{i}] y={y0}..{y1} 中心={(y0+y1)//2}")

    tpl2 = np.array(Image.open(TPL / "2_nte.png").convert("RGB"))
    th2, tw2, _ = tpl2.shape
    print(f"\n2_nte.png = {tw2}x{th2}")

    print(f"\n{'='*72}")
    print("逐页点击勘察")
    print(f"{'='*72}")
    for i, (y0, y1) in enumerate(runs):
        cy = (y0 + y1) // 2
        cx = 30
        sx, sy = c2s(hwnd, cx, cy)
        print(f"\n[{i}] 点击侧栏 y={cy} -> 屏幕 ({sx},{sy})")
        click(sx, sy)
        time.sleep(1.6)

        r2 = R(); user32.GetWindowRect(hwnd, ctypes.byref(r2))
        w2, h2 = r2.r - r2.l, r2.b - r2.t
        got2 = C.capture_region(r2.l, r2.t, w2, h2)
        if not got2:
            print("     抓帧失败")
            continue
        d2, fw2, fh2 = got2
        f2 = np.frombuffer(d2, dtype=np.uint8).reshape(fh2, fw2, 4)[:, :, [2, 1, 0]]
        Image.fromarray(f2).save(OUT / f"nte-page-{i:02d}.png")

        if th2 <= fh2 and tw2 <= fw2:
            sc, mx, my = match_template(f2, tpl2)
            hits = all_hits(f2, tpl2, 0.85, min_dist=40)
            mark = ""
            if sc >= 0.90:
                mark = "  <<<< 命中！"
            print(f"     2_nte score={sc:.4f} pos=({mx},{my}) 候选={len(hits)}{mark}")
            if len(hits) > 1:
                for j, (yy, xx, ss) in enumerate(hits[:4]):
                    print(f"        [{j}] {ss:.4f} @({xx},{yy})")
        else:
            print(f"     窗口 {fw2}x{fh2} 小于模板")

    print(f"\n落盘 nte-page-XX.png（共 {len(runs)} 页）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
