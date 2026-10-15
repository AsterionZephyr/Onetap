import win32gui
parent = 1049334
print("=== ok-ww 的子窗口 ===")
def cb(h, _):
    cls = win32gui.GetClassName(h)
    t = win32gui.GetWindowText(h)
    rc = win32gui.GetWindowRect(h)
    vis = win32gui.IsWindowVisible(h)
    print(f"  child hwnd={h:>10} vis={vis} cls={cls:26s} rect={rc} {t[:40]!r}")
win32gui.EnumChildWindows(parent, cb, None)
