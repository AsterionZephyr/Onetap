"""taskbar_probe.py — 定位任务栏上 ok-ww 的按钮（只读，不点击）

任务栏本身是 'Shell_TrayWnd'，其上每个应用按钮是
'Shell_SecondaryTrayWnd'/'MSTaskSwWClass' 下的 'TaskListThumbnailWnd'
或由 explorer 托管的按钮窗口。较稳的做法：
  1. 找 Shell_TrayWnd 的矩形
  2. 枚举其子孙窗口，打印类名/标题/矩形
  3. 通过标题匹配 OK-WW 找到那个按钮
"""

import sys
import ctypes
from ctypes import wintypes as wt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.WinDLL("user32", use_last_error=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2)

EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
GetClassNameW = user32.GetClassNameW
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowRect = user32.GetWindowRect


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


def cls(h):
    b = ctypes.create_unicode_buffer(512)
    GetClassNameW(h, b, 512)
    return b.value


def txt(h):
    n = GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 2)
    GetWindowTextW(h, b, n + 2)
    return b.value


def rect(h):
    r = RECT()
    if not GetWindowRect(h, ctypes.byref(r)):
        return None
    return r


def main():
    # 1) 找任务栏
    shell = user32.FindWindowW("Shell_TrayWnd", None)
    print(f"Shell_TrayWnd hwnd = {shell}")
    if not shell:
        print("[NG] 未找到任务栏")
        return 1
    r = rect(shell)
    print(f"  任务栏 rect = ({r.left},{r.top})-({r.right},{r.bottom})  "
          f"{r.right-r.left}x{r.bottom-r.top}")

    # 2) 枚举任务栏的所有子孙
    print("\n[任务栏子孙窗口]")
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        c = cls(h)
        t = txt(h)
        rr = rect(h)
        if rr:
            w, hh = rr.right - rr.left, rr.bottom - rr.top
            if w > 5 and hh > 5:
                found.append((h, c, t, rr))
        return True

    EnumChildWindows(shell, cb, 0)
    print(f"  共 {len(found)} 个可见子孙")
    for h, c, t, rr in found:
        # 只打印可能有意义的
        if "OK" in t or "Tray" in c or "Task" in c or "MSTask" in c:
            print(f"   hwnd={h}  class={c}  title=[{t}]  "
                  f"rect=({rr.left},{rr.top})-({rr.right},{rr.bottom})")

    # 3) 专门匹配 OK-WW
    print("\n[标题含 OK-WW 的任务栏窗口]")
    hits = [(h, c, t, rr) for h, c, t, rr in found if "OK-WW" in t or "OK" in t]
    if not hits:
        print("  未找到 —— 任务栏按钮可能由 XAML/DirectUI 绘制，无独立 HWND")
    for h, c, t, rr in hits:
        cx, cy = (rr.left + rr.right) // 2, (rr.top + rr.bottom) // 2
        print(f"   hwnd={h} class={c} title=[{t}]")
        print(f"      rect=({rr.left},{rr.top})-({rr.right},{rr.bottom})  "
              f"{rr.right-rr.left}x{rr.bottom-rr.top}  中心=({cx},{cy})")

    # 4) 顺带看看有没有 UI Automation 可以枚举
    print("\n[任务栏整体几何用于估算]")
    print(f"  任务栏高 = {r.bottom - r.top}，底边 y = {r.bottom}")
    print(f"  屏幕 {user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
