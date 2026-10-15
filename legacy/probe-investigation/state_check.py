"""state_check.py — 只读：报告 ok-ww 与前台的真实状态，并落盘 ok-ww 自身内容

关键：屏幕抓图会抓到遮挡者。本脚本先报告前台，再抓图，
由调用者据前台判断这帧是否可信。不做任何点击。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C

user32 = C.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")


def title_of(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, b, n + 2)
    return b.value


def main():
    wins = C.find_okww_window()
    if not wins:
        print("[NG] ok-ww 窗口未找到 —— 进程可能已退出")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top

    fg = user32.GetForegroundWindow()
    print(f"ok-ww   hwnd={hwnd} pid={pid} rect=({r.left},{r.top})-({r.right},{r.bottom}) {w}x{h}")
    print(f"        visible={bool(user32.IsWindowVisible(hwnd))} iconic={bool(user32.IsIconic(hwnd))}")
    print(f"前台    hwnd={fg}  title=[{title_of(fg)}]")
    print(f"        ok-ww 是否在前台 = {fg == hwnd}")
    print(f"        => 屏幕抓图{'可信' if fg == hwnd else '**不可信（抓到的是前台窗口）**'}")

    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        print("[NG] 抓帧失败")
        return 1
    d, fw, fh = got
    arr = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    out = OUT / "state-now.png"
    Image.fromarray(arr).save(out)
    st = C.frame_stats(d, fw, fh)
    print(f"\n抓帧 {fw}x{fh}  均值RGB={st['mean_rgb']}  色彩数={st['distinct_colors_sampled']}")
    print(f"落盘 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
