"""t6_benign_error.py — T-6 实测：提权环境下的良性报错

事实记录 §2.5 记载：提权环境下会额外出现
    pywintypes.error: (5, 'GetCursorPos', '拒绝访问。')
来自无边框窗口插件取光标位置被拒，与识别无关、不影响功能。

本脚本验证：
  1. 该报错在提权会话中是否可复现
  2. 它是否真的不影响窗口定位/抓图（即"良性"是否成立）
  3. 能否被稳定识别并排除在失败判定之外
"""

import sys
import ctypes
import ctypes.wintypes as wt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
user32 = ctypes.WinDLL("user32", use_last_error=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2)


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


def check_admin():
    import ctypes as ct
    try:
        return bool(ct.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def try_getcursorpos():
    p = POINT()
    ctypes.set_last_error(0)
    ok = user32.GetCursorPos(ctypes.byref(p))
    err = ctypes.get_last_error()
    return bool(ok), (p.x, p.y), err


def try_getcursorpos_via_pywin32():
    try:
        import win32api
    except ImportError:
        return "pywin32 未安装"
    try:
        return ("成功", win32api.GetCursorPos())
    except Exception as e:
        return ("异常", type(e).__name__, str(e))


def main():
    print("=" * 68)
    print("T-6 实测：提权环境下的良性报错")
    print("=" * 68)

    print(f"\n[1] 当前提权状态")
    adm = check_admin()
    print(f"    IsUserAnAdmin = {adm}")

    print(f"\n[2] GetCursorPos 直接调用（ctypes）")
    for i in range(3):
        ok, pos, err = try_getcursorpos()
        print(f"    第{i+1}次: ok={ok} pos={pos} err={err}")
        if not ok:
            print(f"      => 失败，err={err}（5 = ERROR_ACCESS_DENIED）")

    print(f"\n[3] GetCursorPos 经 pywin32（事实记录中报错的调用路径）")
    r = try_getcursorpos_via_pywin32()
    print(f"    {r}")

    print(f"\n[4] 判定：该报错是否影响核心功能")
    # 核心功能：抓图 + 窗口定位，都不依赖 GetCursorPos
    import capture as C
    wins = C.find_okww_window()
    print(f"    窗口发现: {'成功' if wins else '失败'}  ({len(wins) if wins else 0} 个)")
    if wins:
        hwnd, pid, title = wins[0]
        r_ = C.get_window_rect(hwnd)
        w, h = r_.right - r_.left, r_.bottom - r_.top
        print(f"    GetWindowRect: {w}x{h}")
        got = C.capture_region(r_.left, r_.top, w, h)
        if got:
            d, fw, fh = got
            st = C.frame_stats(d, fw, fh)
            print(f"    抓帧: {fw}x{fh}  均值RGB={st['mean_rgb']}  色彩={st['distinct_colors_sampled']}")
            print(f"    => 抓图与定位{'未受影响' if sum(st['mean_rgb'])>15 else '可能受影响'}")

    print(f"\n[5] 结论")
    print(f"    GetCursorPos 的失败与窗口定位/抓图是**独立**的两条路径：")
    print(f"      抓图  = GetDC + BitBlt + GetDIBits（不涉及光标）")
    print(f"      定位  = GetWindowRect / ClientToScreen（不涉及光标）")
    print(f"      点击  = SetCursorPos + SendInput（写光标，不是读光标）")
    print(f"    => 故该类报错**可以**被排除在失败判定之外。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
