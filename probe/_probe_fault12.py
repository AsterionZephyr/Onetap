import sys
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import window, win32
print("== ok-ww 已退出，GUI 还开着 ==")
print("find_okww_window(require_ready=False) ->", window.find_okww_window())
print("find_okww_window(require_ready=True)  ->", window.find_okww_window(require_ready=True))
# 复现 rediscover_hwnd 的危害
class S(dict):
    def get(self,k,d=None): return super().get(k,d)
    def set(self,k,v): self[k]=v
st = S({"hwnd": 13043768, "pid": 41544})
from orchestrator.steps import context
h = context.rediscover_hwnd(st)
print("rediscover_hwnd 返回 hwnd =", h)
print("  -> 是 GUI 自己的窗口吗:", h == 2885578)
if h:
    try:
        from orchestrator import capture
        f = capture.grab_frame(h)
        print("  抓该 hwnd 得到:", f.width, "x", f.height, "均值", f.stats.get("mean_rgb"))
    except Exception as e:
        print("  抓帧异常:", type(e).__name__, str(e)[:120])
