"""nte_launch.py — 正确启动 ok-nte 并勘察

修正上一版：用 'ok-nte' / 'OK-NTE' 精确子串匹配窗口标题，
避免 'Activity'/'Notification' 里的 'nte' 造成误判。
"""

import sys
import time
import subprocess
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")
EXE = r"E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe"


def procs(names=("ok-nte", "pythonw", "msedgewebview2")):
    d = {}
    for n in names:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        d[n] = [(l.split('","')[1], l.split('","')[4].strip('"'))
                for l in o.splitlines() if l.startswith('"')]
    return d


def nte_windows(visible_only=False):
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            t = b.value
            # 严格：必须是 ok-nte / OK-NTE 开头或包含
            if "ok-nte" in t.lower():
                c = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(h, c, 128)
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                v = bool(user32.IsWindowVisible(h))
                if visible_only and not v:
                    return True
                res.append((h, c.value, t, pid.value, v))
        return True

    user32.EnumWindows(cb, 0)
    return res


class R(ctypes.Structure):
    _fields_ = [("l", wt.LONG), ("t", wt.LONG), ("r", wt.LONG), ("b", wt.LONG)]


def rect_of(h):
    r = R()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r


def main():
    print("=" * 72)
    print("ok-nte 启动与勘察")
    print("=" * 72)

    p = procs()
    print(f"[当前] ok-nte 进程={p['ok-nte']}")
    print(f"       窗口={[(x[0], x[2], x[4]) for x in nte_windows()]}")

    if not p["ok-nte"]:
        print(f"\n[启动] {EXE}")
        subprocess.Popen([EXE], cwd=r"E:\TOOLS\ScriptsGames\ok-nte")
        t0 = time.time()
        last = None
        for i in range(90):
            time.sleep(1)
            p = procs()
            w = nte_windows()
            sig = (tuple(p["ok-nte"]), tuple((x[0], x[4]) for x in w))
            if sig != last:
                last = sig
                el = time.time() - t0
                print(f"\n[t={el:5.1f}s] ok-nte 进程数={len(p['ok-nte'])} "
                      f"webview2={len(p['msedgewebview2'])}")
                for pid_, mem in p["ok-nte"]:
                    print(f"        ok-nte pid={pid_} mem={mem}")
                for h, c, t, pid_, v in w:
                    r = rect_of(h)
                    print(f"        hwnd={h} pid={pid_} {r.r-r.l}x{r.b-r.t} "
                          f"vis={v} class={c}")
                    print(f"            title=[{t}]")
            if any(x[4] and (rect_of(x[0]).r - rect_of(x[0]).l) > 300 for x in w):
                print(f"\n[t={time.time()-t0:.1f}s] 主窗口已出现，再等 4 秒稳定")
                time.sleep(4)
                break
    else:
        print("\n[已运行] 跳过启动")

    print("\n" + "=" * 72)
    print("勘察结果")
    print("=" * 72)
    wins = [w for w in nte_windows(visible_only=True)
            if (rect_of(w[0]).r - rect_of(w[0]).l) > 200]
    if not wins:
        print("[NG] 无可见主窗口")
        for h, c, t, pid_, v in nte_windows():
            r = rect_of(h)
            print(f"  候选 hwnd={h} vis={v} {r.r-r.l}x{r.b-r.t} class={c} [{t}]")
        return 1

    for h, c, t, pid_, v in wins:
        r = rect_of(h)
        w_, h_ = r.r - r.l, r.b - r.t
        print(f"\nhwnd={h}  pid={pid_}  class={c}")
        print(f"  title = [{t}]")
        print(f"  rect  = ({r.l},{r.t})-({r.r},{r.b})  {w_}x{h_}")
        print(f"  iconic={bool(user32.IsIconic(h))}  前台={user32.GetForegroundWindow()==h}")
        cnt = [0]

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def ccb(ch, l):
            cnt[0] += 1
            return True

        user32.EnumChildWindows(h, ccb, 0)
        print(f"  子窗口数 = {cnt[0]}")

        got = C.capture_region(r.l, r.t, w_, h_)
        if not got:
            continue
        d, fw, fh = got
        f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
        Image.fromarray(f).save(OUT / "nte-full.png")
        st = C.frame_stats(d, fw, fh)
        print(f"  抓帧 {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")
        print(f"  落盘 nte-full.png")

        from template_probe import match_template
        for name in ["1_nte.png", "2_nte.png"]:
            tp = np.array(Image.open(TPL / name).convert("RGB"))
            th, tw, _ = tp.shape
            if th > fh or tw > fw:
                print(f"  [{name}] {tw}x{th} 比窗口大，跳过")
                continue
            sc, mx, my = match_template(f, tp)
            print(f"  [{name}] {tw}x{th} score={sc:.4f} pos=({mx},{my}) 中心=({mx+tw//2},{my+th//2})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
