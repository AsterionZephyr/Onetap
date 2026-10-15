"""run_daily.py — 端到端：前置校验 -> 置前台 -> 定位「开始」-> 点击

流程（每步都有校验，任一步不过即停手）：
  1. 发现 ok-ww 窗口，读 rect（INV-14：不缓存）
  2. SetForegroundWindow 置前台，并**验证确实生效**
  3. 抓帧 + INV-1 尺寸校验 + 内容校验
  4. 用 2_ww.png 的**文字段**定位「每日任务」行（score 必须 >= 0.95）
  5. 同行扫描「开始」按钮，交叉验证（按钮 y 落在行内）
  6. 遮挡判定：确认目标屏幕坐标处最顶层窗口是 ok-ww
  7. 点击

用法：python run_daily.py [--dry-run]
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

# ---------- SendInput ----------
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


def set_foreground(hwnd):
    """置前台并验证生效。"""
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    return user32.GetForegroundWindow() == hwnd


def client_to_screen(hwnd, cx, cy):
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = POINT(cx, cy)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def top_window_at(x, y):
    """取屏幕坐标处最顶层的窗口 hwnd。"""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = POINT(x, y)
    h = user32.WindowFromPoint(p)
    # WindowFromPoint 可能返回子窗口，向上找顶层
    GA_ROOT = 2
    return user32.GetAncestor(h, GA_ROOT)


def click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y)
    time.sleep(0.08)
    nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    for flag in (0x0001 | 0x8000, 0x0002, 0x0004):
        inp = INPUT()
        inp.type = 0
        inp.mi.dx, inp.mi.dy, inp.mi.dwFlags = nx, ny, flag
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.04)


def main():
    dry = "--dry-run" in sys.argv
    print("=" * 68)
    print("端到端：置前台 -> 定位「每日任务 · 开始」-> 点击" + ("  [DRY RUN]" if dry else ""))
    print("=" * 68)

    # 1) 发现窗口
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww 窗口")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    print(f"\n[1] ok-ww hwnd={hwnd} pid={pid}")
    print(f"    rect=({r.left},{r.top})-({r.right},{r.bottom})  {w}x{h}")

    # 2) 置前台
    print(f"\n[2] SetForegroundWindow ...")
    ok = set_foreground(hwnd)
    print(f"    置前台结果 = {ok}  (GetForegroundWindow={user32.GetForegroundWindow()})")
    if not ok:
        print("    [NG] 未能将 ok-ww 置于前台，中止")
        return 1
    print("    [OK] ok-ww 已在前台")

    # 3) 抓帧 + 校验
    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        print("\n[3] [NG] 抓帧失败")
        return 1
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    print(f"\n[3] 抓帧 {fw}x{fh}")
    if (fw, fh) != (w, h):
        print(f"    [NG] INV-1 失败：帧 {fw}x{fh} != 窗口 {w}x{h}")
        return 1
    print("    [OK] INV-1 帧尺寸 == 窗口 rect")
    st = C.frame_stats(d, fw, fh)
    if sum(st["mean_rgb"]) < 15:
        print("    [NG] 帧近乎全黑（INV-13），中止")
        return 1
    print(f"    [OK] 内容校验通过 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")

    # 4) 文字段定位「每日任务」行
    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape
    sub = tpl[:, 9:9 + 98]                     # 日历+每日任务 文字段
    sc, mx, my = match_template(frame, sub)
    print(f"\n[4] 「每日任务」文字段匹配 score={sc:.4f} pos=({mx},{my})")
    if sc < 0.95:
        print(f"    [NG] 分数 {sc:.4f} < 0.95，不敢据以点击，中止")
        return 1
    print(f"    [OK] 定位成功：行 y={my}..{my+th}  中心 y={my+th//2}")

    # 5) 同行扫描「开始」按钮
    by0, by1 = max(0, my - 5), min(fh, my + th + 5)
    band = frame[by0:by1]
    g = band.astype(np.float32).mean(axis=2)
    bright = g > 200
    colsum = bright.sum(axis=0)
    cols = np.where(colsum > (by1 - by0) * 0.35)[0]
    if not len(cols):
        print("\n[5] [NG] 该行未找到白色按钮块，中止")
        return 1
    groups = []
    s = prev = cols[0]
    for c in cols[1:]:
        if c - prev > 8:
            groups.append((s, prev)); s = c
        prev = c
    groups.append((s, prev))
    bx0, bx1 = groups[-1]
    bcx = (bx0 + bx1) // 2
    sub_b = bright[:, bx0:bx1 + 1]
    rows = np.where(sub_b.sum(axis=1) > 3)[0]
    bcy = by0 + (rows.min() + rows.max()) // 2
    print(f"\n[5] 「开始」按钮 x={bx0}..{bx1} y={by0+rows.min()}..{by0+rows.max()}")
    print(f"    中心（窗口内）= ({bcx},{bcy})")
    if not (my <= bcy <= my + th):
        print(f"    [NG] 交叉验证失败：按钮 y={bcy} 不在行 {my}..{my+th} 内")
        return 1
    print("    [OK] 交叉验证通过：按钮与文字在同一行")

    # 6) 遮挡判定
    sx, sy = client_to_screen(hwnd, bcx, bcy)
    print(f"\n[6] 屏幕坐标 = ({sx},{sy})")
    top = top_window_at(sx, sy)
    print(f"    该坐标处最顶层窗口 hwnd = {top}")
    print(f"    是 ok-ww = {top == hwnd}")
    if top != hwnd:
        print(f"    [NG] 目标坐标被其他窗口占据（hwnd={top}），点击会打到别的窗口，中止")
        return 1
    print("    [OK] 目标坐标未被遮挡")

    # 裁图确认
    crop = frame[max(0, bcy - 30):bcy + 30, max(0, bcx - 100):bcx + 80]
    Image.fromarray(crop).save(OUT / "about-to-click.png")
    print(f"    落盘 about-to-click.png 供核对")

    if dry:
        print("\n[DRY RUN] 未执行点击。")
        return 0

    # 7) 点击
    print(f"\n[7] 点击 ({sx},{sy}) ...")
    click(sx, sy)
    time.sleep(0.8)

    s1 = C.get_window_rect(hwnd)
    print(f"    点击后窗口 rect = ({s1.left},{s1.top})-({s1.right},{s1.bottom}) "
          f"{s1.right-s1.left}x{s1.bottom-s1.top}")
    fg = user32.GetForegroundWindow()
    print(f"    点击后前台 = {fg}  (ok-ww={fg == hwnd})")
    print(f"    ok-ww 仍存活 = {bool(user32.IsWindow(hwnd))}")
    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
