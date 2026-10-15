"""watch_autoclose.py — 受控观测：任务跑完后 ok-ww 是否自动退出

与上次的区别（上次无法排除是游戏崩溃所致）：
  本次持续采样，记录**退出的确切时刻与顺序**：
    - 是 ok-ww(pythonw) 先退，还是游戏先退？
    - 退出前窗口发生了什么（尺寸变化 / 消失 / 新建）？
    - ok-ww.exe（第一层）是否再次出现？

持续采样 + 事件记录，直到 ok-ww 消失或超时。
"""

import sys
import time
import subprocess
import ctypes
import ctypes.wintypes as wt
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
user32 = ctypes.WinDLL("user32", use_last_error=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2)

WATCH_PROC = ["pythonw", "ok-ww", "Client-Win64-Shipping", "launcher"]
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 900


def procs():
    d = {}
    for n in WATCH_PROC:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        rows = []
        for line in o.splitlines():
            if line.startswith('"'):
                p = line.split('","')
                rows.append((p[1], p[4].strip('"')))
        d[n] = rows
    return d


def okww_wins():
    res = []

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
                class R(ctypes.Structure):
                    _fields_ = [("l", wt.LONG), ("t", wt.LONG),
                                ("r", wt.LONG), ("b", wt.LONG)]
                r = R()
                user32.GetWindowRect(h, ctypes.byref(r))
                res.append((h, c.value, t, r.r - r.l, r.b - r.t))
        return True

    user32.EnumWindows(cb, 0)
    return res


def ts():
    return datetime.now().strftime("%H:%M:%S")


def sig(p, w):
    return (tuple(sorted(p.get("pythonw", []))),
            tuple(sorted(p.get("ok-ww", []))),
            tuple(sorted(p.get("Client-Win64-Shipping", []))),
            tuple(sorted((x[0], x[3], x[4]) for x in w)))


def main():
    print("=" * 72)
    print("受控观测：ok-ww 自动关闭")
    print("=" * 72)
    print(f"开始时间 {ts()}   最长观测 {DURATION}s   每 2s 采样")
    print()

    t0 = time.time()
    last = None
    last_seen_alive = None
    events = []

    while time.time() - t0 < DURATION:
        p = procs()
        w = okww_wins()
        s = sig(p, w)
        el = time.time() - t0

        if s != last:
            last = s
            pyw = p.get("pythonw", [])
            okw = p.get("ok-ww", [])
            gam = p.get("Client-Win64-Shipping", [])
            line = (f"[{ts()} +{el:6.1f}s] pythonw={len(pyw)} ok-ww={len(okw)} "
                    f"game={len(gam)}")
            print(line)
            for h, c, t, ww, wh in w:
                print(f"              窗口 {ww}x{wh} class={c} [{t}]")
            if pyw:
                print(f"              pythonw pid={[x[0] for x in pyw]} mem={[x[1] for x in pyw]}")
            events.append((el, line))

        alive = bool(p.get("pythonw"))
        if alive:
            last_seen_alive = el
        elif last_seen_alive is not None and last_seen_alive > 5:
            print()
            print("=" * 72)
            print(f"[{ts()} +{el:.1f}s] *** pythonw 已消失 —— ok-ww 退出 ***")
            print(f"    最后存活时刻: +{last_seen_alive:.1f}s")
            print(f"    退出后状态: ok-ww={len(p.get('ok-ww',[]))} "
                  f"game={len(p.get('Client-Win64-Shipping',[]))}")
            print()
            print("  退出顺序判定：")
            print(f"    观测到的最后活动窗口数 = {len(w)}")
            print("=" * 72)
            return 0

        time.sleep(2)

    print()
    print("=" * 72)
    print(f"[{ts()}] 观测超时（{DURATION}s），ok-ww 仍在运行")
    p = procs()
    print(f"  pythonw={len(p.get('pythonw',[]))} game={len(p.get('Client-Win64-Shipping',[]))}")
    print("=" * 72)
    return 2


if __name__ == "__main__":
    sys.exit(main())
