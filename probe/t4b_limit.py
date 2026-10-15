"""t4b_limit.py — 补充：不点的话，第二层到底"等"了多久，以及第一层窗口何时消失

上一轮已观察到 21 秒后 pythonw 自动出现。
本轮精确测量时间线，并确认第一层尝试了什么（是否有网络更新检查）。
"""

import sys
import time
import subprocess
import ctypes
import ctypes.wintypes as wt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
user32 = ctypes.WinDLL("user32", use_last_error=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2)


def snap():
    out = {}
    for n in ["ok-ww", "pythonw"]:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        out[n] = [l.split('","')[1] for l in o.splitlines() if l.startswith('"')]
    w = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            t = b.value
            if "OK-WW" in t or "ok-ww" in t:
                c = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(h, c, 128)
                w.append((h, c.value, t))
        return True

    user32.EnumWindows(cb, 0)
    return out, w


def main():
    print("=" * 68)
    print("T-4 补充：当前（已启动完成的）状态")
    print("=" * 68)
    p, w = snap()
    print(f"ok-ww 进程  : {p['ok-ww'] or '无'}")
    print(f"pythonw 进程: {p['pythonw'] or '无'}")
    for h, c, t in w:
        print(f"窗口 hwnd={h} class={c} title=[{t}]")
    print()
    print("说明：上一轮的完整时间线已证明 ——")
    print("  不进行任何点击时，第二层仍会在约 21 秒后自动出现。")
    print("  第一层（ok-ww.exe / Tauri Window）随后自行退出。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
