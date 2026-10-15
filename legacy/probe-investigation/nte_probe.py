"""nte_probe.py — ok-nte 适配勘察（只读）

目标：
  1. 启动 ok-nte，观察进程/窗口结构（是否也是两层？窗口持有者是谁？）
  2. 取窗口 rect / class / title / DPI
  3. 抓整窗并落盘，供肉眼比对
  4. 用 1_nte.png / 2_nte.png 做初步匹配，看分数与候选数
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


def procs():
    d = {}
    for n in ["ok-nte", "ok-ww", "pythonw", "ok-nte-web", "msedgewebview2"]:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        d[n] = [(l.split('","')[1], l.split('","')[4].strip('"'))
                for l in o.splitlines() if l.startswith('"')]
    return d


def find_nte_windows():
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            t = b.value
            if "nte" in t.lower() or "NTE" in t:
                c = ctypes.create_unicode_buffer(128)
                user32.GetClassNameW(h, c, 128)
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                res.append((h, c.value, t, pid.value,
                            bool(user32.IsWindowVisible(h))))
        return True

    user32.EnumWindows(cb, 0)
    return res


def main():
    print("=" * 72)
    print("ok-nte 适配勘察")
    print("=" * 72)

    p0 = procs()
    print(f"\n[启动前] ok-nte={len(p0['ok-nte'])} pythonw={len(p0['pythonw'])} "
          f"webview2={len(p0['msedgewebview2'])}")
    print(f"          窗口: {find_nte_windows()}")

    if not p0["ok-nte"] and not find_nte_windows():
        print(f"\n[启动] {EXE}")
        subprocess.Popen([EXE], cwd=r"E:\TOOLS\ScriptsGames\ok-nte")
        t0 = time.time()
        last = None
        for i in range(60):
            time.sleep(1)
            p = procs()
            w = find_nte_windows()
            sig = (tuple(p["ok-nte"]), tuple(w), len(p["msedgewebview2"]))
            if sig != last:
                last = sig
                el = time.time() - t0
                print(f"\n[t={el:5.1f}s] ok-nte={len(p['ok-nte'])} "
                      f"webview2={len(p['msedgewebview2'])}")
                for pid_, mem in p["ok-nte"]:
                    print(f"        ok-nte pid={pid_} mem={mem}")
                for h, c, t, pid_, v in w:
                    class R(ctypes.Structure):
                        _fields_ = [("l", wt.LONG), ("t", wt.LONG),
                                    ("r", wt.LONG), ("b", wt.LONG)]
                    r = R()
                    user32.GetWindowRect(h, ctypes.byref(r))
                    print(f"        窗口 hwnd={h} pid={pid_} {r.r-r.l}x{r.b-r.t} "
                          f"vis={v} class={c}")
                    print(f"             title=[{t}]")
            if w and any(x[4] for x in w) and i > 6:
                print(f"\n[t={time.time()-t0:.1f}s] 窗口已出现，再观察 5 秒")
                time.sleep(5)
                break
    else:
        print("\n[已运行] 跳过启动")

    # 勘察
    print("\n" + "=" * 72)
    print("窗口勘察")
    print("=" * 72)
    wins = [w for w in find_nte_windows() if w[4]]
    if not wins:
        print("[NG] 无可见的 ok-nte 窗口")
        return 1

    for h, c, t, pid_, v in wins:
        class R(ctypes.Structure):
            _fields_ = [("l", wt.LONG), ("t", wt.LONG),
                        ("r", wt.LONG), ("b", wt.LONG)]
        r = R()
        user32.GetWindowRect(h, ctypes.byref(r))
        w_, h_ = r.r - r.l, r.b - r.t
        print(f"\nhwnd={h} pid={pid_} class={c}")
        print(f"  title=[{t}]")
        print(f"  rect=({r.l},{r.t})-({r.r},{r.b})  {w_}x{h_}")
        print(f"  visible={v} iconic={bool(user32.IsIconic(h))}")
        print(f"  前台={user32.GetForegroundWindow()==h}")

        # 子窗口数
        cnt = [0]

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def ccb(ch, l):
            cnt[0] += 1
            return True

        user32.EnumChildWindows(h, ccb, 0)
        print(f"  子窗口数={cnt[0]}")

        if w_ > 100 and h_ > 100:
            got = C.capture_region(r.l, r.t, w_, h_)
            if got:
                d, fw, fh = got
                f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
                Image.fromarray(f).save(OUT / "nte-full.png")
                st = C.frame_stats(d, fw, fh)
                print(f"  抓帧 {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_stampled'] if False else st['distinct_colors_sampled']}")
                print(f"  落盘 nte-full.png")

                from template_probe import match_template
                for name in ["1_nte.png", "2_nte.png"]:
                    tp = np.array(Image.open(TPL / name).convert("RGB"))
                    th, tw, _ = tp.shape
                    if th > fh or tw > fw:
                        print(f"  [{name}] {tw}x{th} 比窗口还大，跳过")
                        continue
                    sc, mx, my = match_template(f, tp)
                    print(f"  [{name}] {tw}x{th}  score={sc:.4f}  pos=({mx},{my})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
