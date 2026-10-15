import sys
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import win32
h = 13043768
r = win32.get_window_rect(h)
print("ok-ww rect:", (r.left,r.top,r.right,r.bottom))
# 采样窗口矩形内若干点，看最顶层是谁
for (x,y,tag) in [(r.left+30, r.top+30, "左上"), (r.left+(r.right-r.left)//2, r.top+(r.bottom-r.top)//2, "中心"),
                  (r.left+1300, r.top+90, "开始按钮附近")]:
    t = win32.top_window_at(x,y)
    print(f"  {tag} ({x},{y}) 最顶层 hwnd={t}", "= ok-ww" if t==h else "!= ok-ww")
import win32gui
print("=== 枚举可见顶层窗口 ===")
def cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        t = win32gui.GetWindowText(hwnd)
        try:
            cls = win32gui.GetClassName(hwnd)
            rc = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        if rc[2]-rc[0] > 200 and rc[3]-rc[1] > 100:
            print(f"  hwnd={hwnd:>10} cls={cls:28s} rect={rc} title={t[:50]!r}")
win32gui.EnumWindows(cb, None)
