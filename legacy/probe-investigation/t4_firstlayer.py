"""t4_firstlayer.py — T-4 实测：人工不点第一层会怎样

观察项：
  1. 启动 ok-ww.exe 后，进程/窗口如何演化（第一层 -> 第二层）
  2. 若一直不点击，第一层是否停在检查更新界面
  3. 是否超时、超时后行为
  4. 第二层（pythonw 窗口）是否会在无人干预下自动出现

只观察，不点击。
"""

import sys
import time
import subprocess
import ctypes
import ctypes.wintypes as wt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.WinDLL("user32", use_last_error=True)
ctypes.windll.shcore.SetProcessDpiAwareness(2)

EXE = r"E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe"


def procs():
    """返回 {name: [(pid, mem)]}"""
    out = {}
    for n in ["ok-ww", "pythonw", "python"]:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        rows = []
        for line in o.splitlines():
            if line.startswith('"'):
                p = line.split('","')
                rows.append((p[1], p[4].strip('"')))
        out[n] = rows
    return out


def wins_of():
    """列出标题含 OK-WW / ok-ww 的顶层窗口"""
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            t = b.value
            if "OK-WW" in t or "ok-ww" in t:
                c = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(h, c, 256)
                res.append((h, c.value, t, bool(user32.IsWindowVisible(h))))
        return True

    user32.EnumWindows(cb, 0)
    return res


def rect_of(h):
    class R(ctypes.Structure):
        _fields_ = [("l", wt.LONG), ("t", wt.LONG), ("r", wt.LONG), ("b", wt.LONG)]
    r = R()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r.r - r.l, r.b - r.t


def main():
    print("=" * 70)
    print("T-4 实测：启动 ok-ww，观察『人工不点第一层』的行为")
    print("=" * 70)

    p0 = procs()
    print(f"\n[启动前] ok-ww={len(p0['ok-ww'])}  pythonw={len(p0['pythonw'])}")
    print(f"          已有窗口: {wins_of()}")

    print(f"\n[启动] {EXE}")
    try:
        subprocess.Popen([EXE], cwd=r"E:\TOOLS\ScriptsGames\ok-ww")
    except Exception as e:
        print(f"  [NG] 启动失败：{e}")
        return 1
    t_start = time.time()

    last = None
    for i in range(90):          # 最多观察 90 秒
        time.sleep(1)
        el = time.time() - t_start
        p = procs()
        w = wins_of()
        sig = (tuple(p["ok-ww"]), tuple(p["pythonw"]), tuple(w))
        if sig != last:
            last = sig
            print(f"\n[t={el:5.1f}s] 状态变化:")
            print(f"    ok-ww  进程: {p['ok-ww'] if p['ok-ww'] else '无'}")
            print(f"    pythonw 进程: {p['pythonw'] if p['pythonw'] else '无'}")
            for h, c, t, v in w:
                sz = rect_of(h)
                print(f"    窗口 hwnd={h} class={c} vis={v} {sz[0]}x{sz[1]}")
                print(f"         title=[{t}]")
        # 若第二层出现且窗口稳定，再观察 10 秒后收尾
        if any("Qt" in c for _, c, _, _ in w) and i > 5:
            print(f"\n[t={el:5.1f}s] 第二层（Qt 窗口）已出现，继续观察 8 秒确认稳定…")
            for j in range(8):
                time.sleep(1)
                ww = wins_of()
                p2 = procs()
                print(f"    +{j+1}s  ok-ww={len(p2['ok-ww'])} pythonw={len(p2['pythonw'])} "
                      f"窗口={[(x[0], rect_of(x[0])) for x in ww]}")
            break
    else:
        print(f"\n[t={time.time()-t_start:.1f}s] 观察窗口到期")

    print("\n" + "=" * 70)
    print("T-4 观察结束（全程未点击任何东西）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
