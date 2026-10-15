import win32gui
def cb(h, _):
    if win32gui.IsWindowVisible(h):
        rc = win32gui.GetWindowRect(h)
        if rc[2]-rc[0] > 200 and rc[3]-rc[1] > 100:
            print(f"  hwnd={h:>10} cls={win32gui.GetClassName(h):26s} rect={rc} {win32gui.GetWindowText(h)[:40]!r}")
win32gui.EnumWindows(cb, None)
print("前台:", win32gui.GetForegroundWindow(), win32gui.GetWindowText(win32gui.GetForegroundWindow()))
