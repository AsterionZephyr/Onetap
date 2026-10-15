"""click_step1.py — 阶段三第一步：点击侧栏导航图标（T-8 / T-2 验证）

安全措施：
  - 点击前记录：窗口 rect、前台、帧校验
  - 用 ClientToScreen 换算坐标（不用手算）
  - 点击后重新读取状态，确认尺寸未变、前台正确
  - 落盘前后两帧，供肉眼确认确实发生了页面跳转

只点侧栏导航图标（1_ww）。不碰「开始」。
"""

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C
from template_probe import capture_okww, match_template, OUT_DIR

user32 = C.user32
gdi32 = C.gdi32
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# --- SendInput 绑定 ---
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


MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


def get_screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def move_and_click(x, y):
    """真实光标：SetCursorPos + SendInput（绝对归一化坐标）。"""
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    sw, sh = get_screen_size()
    nx = int(x * 65535 / (sw - 1))
    ny = int(y * 65535 / (sh - 1))
    for flag in (MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_LEFTDOWN,
                 MOUSEEVENTF_LEFTUP):
        inp = INPUT()
        inp.type = 0
        inp.mi.dx = nx
        inp.mi.dy = ny
        inp.mi.dwFlags = flag
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.03)


def client_to_screen(hwnd, cx, cy):
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = POINT(cx, cy)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def state(hwnd):
    r = C.get_window_rect(hwnd)
    return {
        "rect": (r.left, r.top, r.right, r.bottom),
        "w": r.right - r.left, "h": r.bottom - r.top,
        "fg": user32.GetForegroundWindow(),
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "iconic": bool(user32.IsIconic(hwnd)),
    }


def main():
    print("=" * 66)
    print("阶段三 · 第一步：点击侧栏导航图标")
    print("=" * 66)

    hwnd, pid, title, r, fw, fh, frame = capture_okww()
    print(f"\n[点击前] hwnd={hwnd} pid={pid}")
    s0 = state(hwnd)
    print(f"  rect   = {s0['rect']}  =>  {s0['w']}x{s0['h']}")
    print(f"  前台   = {s0['fg']}  (是本窗口={s0['fg']==hwnd})")
    print(f"  visible={s0['visible']}  iconic={s0['iconic']}")

    # 保存"点击前"帧
    Image.fromarray(frame).save(OUT_DIR / "before-click.png")

    # --- 匹配 1_ww ---
    tpl = np.array(Image.open(r"E:\TOOLS\ScriptsGames\Onetap\templates\1_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape
    score, mx, my = match_template(frame, tpl)
    print(f"\n[匹配] 1_ww  score={score:.4f}  pos=({mx},{my})  尺寸={tw}x{th}")
    if score < 0.9:
        print("  [NG] 匹配分数过低，中止（不得用不可信的坐标点击）")
        return 1

    # --- INV-1：帧尺寸校验 ---
    if (fw, fh) != (s0["w"], s0["h"]):
        print(f"  [NG] INV-1 失败：帧 {fw}x{fh} != 窗口 {s0['w']}x{s0['h']}，中止")
        return 1
    print(f"  [OK] INV-1 帧尺寸 == 窗口 rect")

    # --- 坐标 ---
    tcx, tcy = mx + tw // 2, my + th // 2
    sx, sy = client_to_screen(hwnd, tcx, tcy)
    print(f"\n[坐标] 窗口内中心 = ({tcx},{tcy})")
    print(f"       换算屏幕坐标 = ({sx},{sy})")
    sw, sh = get_screen_size()
    if not (0 <= sx < sw and 0 <= sy < sh):
        print(f"  [NG] 屏幕坐标越界（屏幕 {sw}x{sh}），中止")
        return 1
    print(f"  [OK] 在屏幕范围内（{sw}x{sh}）")

    # --- INV-8：点击前重新判定前台 ---
    fg_now = user32.GetForegroundWindow()
    print(f"\n[前台复核] 点击前再取一次前台 = {fg_now}  (是 ok-ww={fg_now==hwnd})")
    if fg_now != hwnd:
        print("  [!!] 窗口不在前台，真实光标点击可能落到别处")
        print("       仍继续（将立即用前后帧对比验证是否生效）")

    # --- 点击 ---
    print(f"\n[执行] 移动到 ({sx},{sy}) 并左键单击")
    time.sleep(0.2)
    move_and_click(sx, sy)
    print("  已发送")
    time.sleep(1.2)

    # --- 点击后状态 ---
    print(f"\n[点击后]")
    s1 = state(hwnd)
    print(f"  rect   = {s1['rect']}  =>  {s1['w']}x{s1['h']}")
    print(f"  前台   = {s1['fg']}")
    if s1["w"] != s0["w"] or s1["h"] != s0["h"]:
        print(f"  [!!] INV-2：窗口尺寸发生了变化！{s0['w']}x{s0['h']} -> {s1['w']}x{s1['h']}")
    else:
        print(f"  [OK] 窗口尺寸未变")

    # 重新抓帧
    got = C.capture_region(r.left, r.top, s1["w"], s1["h"])
    if got:
        d, w2, h2 = got
        arr = np.frombuffer(d, dtype=np.uint8).reshape(h2, w2, 4)[:, :, [2, 1, 0]]
        Image.fromarray(arr).save(OUT_DIR / "after-click.png")
        diff = np.abs(arr.astype(np.int16) - frame[:h2, :w2].astype(np.int16)).mean()
        print(f"  帧差异（平均绝对差）={diff:.2f}")
        if diff < 0.5:
            print("  [!!] 前后帧几乎一致 —— 点击**可能未生效**")
        else:
            print(f"  [OK] 画面发生了变化，点击很可能已生效")

    # 再匹配一次 1_ww，看图标位置是否变化
    got2 = C.capture_region(r.left, r.top, s1["w"], s1["h"])
    if got2:
        d2, w3, h3 = got2
        a2 = np.frombuffer(d2, dtype=np.uint8).reshape(h3, w3, 4)[:, :, [2, 1, 0]]
        if tw <= w3 and th <= h3:
            r2 = match_template(a2, tpl)
            print(f"  点击后 1_ww 匹配: score={r2[0]:.4f} pos=({r2[1]},{r2[2]})")

    print("\n[落盘] before-click.png / after-click.png")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
