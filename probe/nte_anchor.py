"""nte_anchor.py — 为 ok-nte 采集「日常任务」文字锚点，并验证其唯一性

思路（沿用 ok-ww 的教训）：
  - 不用裸按钮作锚点（2_nte.png 在其他页也存在）
  - 改用「日常任务」文字作锚点（页面标题，具有鉴别力）
  - 采集后立即验证：该锚点在当前页是否唯一

同时探测侧栏能否展开（为可选方案留证）。
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
from nte_main import find_nte_layer2, all_hits, R

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")


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
    Image.fromarray(f).save(OUT / "nte-anchor-src.png")

    # 先导航到「日常任务」页（侧栏 y=329）
    def c2s(cx, cy):
        class P(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = P(cx, cy); user32.ClientToScreen(hwnd, ctypes.byref(p))
        return p.x, p.y

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
        user32.SetCursorPos(x, y); time.sleep(0.1)
        nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
        for fl in (0x0001 | 0x8000, 0x0002, 0x0004):
            i = IN(); i.type = 0
            i.mi.dx, i.mi.dy, i.mi.fl = nx, ny, fl
            user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(IN))
            time.sleep(0.05)

    sx, sy = c2s(30, 329)
    print(f"导航：点击侧栏 y=329 -> ({sx},{sy})")
    click(sx, sy)
    time.sleep(1.6)

    r2 = R(); user32.GetWindowRect(hwnd, ctypes.byref(r2))
    w2, h2 = r2.r - r2.l, r2.b - r2.t
    got2 = C.capture_region(r2.l, r2.t, w2, h2)
    d2, fw2, fh2 = got2
    f2 = np.frombuffer(d2, dtype=np.uint8).reshape(fh2, fw2, 4)[:, :, [2, 1, 0]]
    Image.fromarray(f2).save(OUT / "nte-daily-page.png")
    print(f"导航后 {fw2}x{fh2}  落盘 nte-daily-page.png")

    # 用 2_nte.png 确认是这一页
    tpl2 = np.array(Image.open(TPL / "2_nte.png").convert("RGB"))
    sc2, mx2, my2 = match_template_safe(f2, tpl2)
    print(f"2_nte.png 确认 score={sc2:.4f} pos=({mx2},{my2})")
    if sc2 < 0.9:
        print("[NG] 未能导航到目标页")
        return 1

    # 现在从这一页裁出「日常任务」文字作为锚点
    # 由整窗图目视：文字在左上，约 x=100..210, y=93..133
    # 用扫描法精确定位：在顶部区域找文字行
    top = f2[80:150, 80:400]
    g = top.astype(np.float32).mean(axis=2)
    bright = g > 140
    rows = np.where(bright.sum(axis=1) > 3)[0]
    cols = np.where(bright.sum(axis=0) > 1)[0]
    if not len(rows) or not len(cols):
        print("[NG] 顶部未找到文字")
        return 1
    y0, y1 = 80 + rows.min(), 80 + rows.max()
    x0, x1 = 80 + cols.min(), 80 + cols.max()
    print(f"\n顶部文字范围 窗口内 x={x0}..{x1} y={y0}..{y1}  ({x1-x0+1}x{y1-y0+1})")

    # 裁出锚点（含少量边距）
    ax0, ay0 = max(0, x0 - 4), max(0, y0 - 4)
    ax1, ay1 = min(fw2, x1 + 5), min(fh2, y1 + 5)
    anchor = f2[ay0:ay1, ax0:ax1]
    Image.fromarray(anchor).save(OUT / "nte-anchor-daily.png")
    print(f"锚点尺寸 {anchor.shape[1]}x{anchor.shape[0]}  落盘 nte-anchor-daily.png")

    # 唯一性检查
    hits = all_hits(f2, anchor, 0.90, min_dist=20)
    print(f"\n唯一性检查（>=0.90）: {len(hits)} 个候选")
    for i, (yy, xx, ss) in enumerate(hits[:6]):
        print(f"  [{i}] {ss:.4f} @({xx},{yy})")
    if len(hits) == 1:
        print("  => [OK] 唯一，可作锚点")
        # 保存为正式资产
        Image.fromarray(anchor).save(TPL / "3_nte_daily.png")
        print(f"  => 已保存为 templates/3_nte_daily.png")
    elif len(hits) > 1:
        print("  => [!!] 不唯一，需缩小或换锚点")
    else:
        print("  => [!!] 无命中（阈值过高？）")


def match_template_safe(frame, tpl):
    from template_probe import match_template
    return match_template(frame, tpl)


if __name__ == "__main__":
    from template_probe import match_template
    sys.exit(main())
