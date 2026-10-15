"""diag_fg.py — 诊断当前屏幕状态：ok-ww 是否被遮挡（只读）"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C

user32 = C.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)


def win_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def win_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def main():
    print("=" * 66)
    print("前台/遮挡诊断")
    print("=" * 66)

    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww 窗口")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    ww, wh = r.right - r.left, r.bottom - r.top
    print(f"\nok-ww hwnd={hwnd} pid={pid}")
    print(f"  rect = ({r.left},{r.top})-({r.right},{r.bottom})  {ww}x{wh}")
    print(f"  visible={bool(user32.IsWindowVisible(hwnd))}  iconic={bool(user32.IsIconic(hwnd))}")

    fg = user32.GetForegroundWindow()
    print(f"\n当前前台 hwnd={fg}")
    print(f"  title = [{win_title(fg)}]")
    print(f"  class = [{win_class(fg)}]")
    print(f"  是 ok-ww = {fg == hwnd}")
    fr = C.get_window_rect(fg)
    if fr:
        print(f"  rect  = ({fr.left},{fr.top})-({fr.right},{fr.bottom})  "
              f"{fr.right-fr.left}x{fr.bottom-fr.top}")

    # 前台窗口是否覆盖了 ok-ww？
    if fr:
        ox = max(0, min(r.right, fr.right) - max(r.left, fr.left))
        oy = max(0, min(r.bottom, fr.bottom) - max(r.top, fr.top))
        if ox > 0 and oy > 0:
            area = ox * oy
            total = ww * wh
            print(f"\n  与 ok-ww 的重叠区域 = {ox}x{oy} = {area} px"
                  f"  占 ok-ww 的 {100*area/total:.1f}%")
            if area > 0.5 * total:
                print("  => ok-ww 大部分被遮挡，屏幕抓图抓到的会是遮挡者")
        else:
            print("\n  前台窗口与 ok-ww 不重叠")

    # 抓一张看实际内容
    got = C.capture_region(r.left, r.top, ww, wh)
    if got:
        d, w, h = got
        arr = np.frombuffer(d, dtype=np.uint8).reshape(h, w, 4)[:, :, [2, 1, 0]]
        Image.fromarray(arr).save(Path(r"E:\TOOLS\ScriptsGames\Onetap\probe") / "diag-fg.png")
        g = arr.astype(np.float32).mean(axis=2)
        print(f"\n[抓帧] {w}x{h}  均值={g.mean():.1f}  落盘 diag-fg.png")

        # ok-ww 的左上角在标题栏附近有 'OK-WW v3.6.7 China' 字样
        # 用 1_ww 模板再匹配一次看分数
        from template_probe import match_template
        tpl = np.array(Image.open(
            r"E:\TOOLS\ScriptsGames\Onetap\templates\1_ww.png").convert("RGB"))
        sc, mx, my = match_template(arr, tpl)
        print(f"[1_ww 匹配] score={sc:.4f} pos=({mx},{my})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
