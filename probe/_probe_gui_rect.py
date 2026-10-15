import ctypes, time
from ctypes import wintypes as wt
u = ctypes.windll.user32
u.SetProcessDPIAware()
h = 2294568
r = wt.RECT()
u.GetWindowRect(wt.HWND(h), ctypes.byref(r))
print("窗口 rect (物理屏幕坐标):", r.left, r.top, r.right, r.bottom,
      " 尺寸", r.right-r.left, "x", r.bottom-r.top)
print("客户区尺寸:")
cr = wt.RECT()
u.GetClientRect(wt.HWND(h), ctypes.byref(cr))
print("   ", cr.right-cr.left, "x", cr.bottom-cr.top)
# 客户区左上角换算到屏幕
pt = wt.POINT(0,0)
u.ClientToScreen(wt.HWND(h), ctypes.byref(pt))
print("客户区屏幕原点:", pt.x, pt.y)
print("窗口在前台吗:", u.GetForegroundWindow() == h)
