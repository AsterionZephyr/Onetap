"""observe_v2.py — 观测运行中的 ok-ww（强制前台 + 逐次验证）

上一版的错误：ok-ww 失去前台，抓到的其实是遮挡窗口，
            "面板稳定" 是假的稳定。
本版：每轮都置前台并**验证**，只有确认抓到 ok-ww 才算数。
"""

import sys
import time
import subprocess
import ctypes
import ctypes.wintypes as wt
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 300

from template_probe import match_template


def procs():
    d = {}
    for n in ["pythonw", "ok-ww", "Client-Win64-Shipping"]:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        d[n] = [l.split('","')[1] for l in o.splitlines() if l.startswith('"')]
    return d


def main():
    print("=" * 76)
    print("观测 v2：强制前台 + 逐次验证抓到的是 ok-ww")
    print("=" * 76)

    side = np.array(Image.open(TPL / "1_ww.png").convert("RGB"))
    t0 = time.time()
    last = None
    n_saved = 0
    bad_frames = 0

    while time.time() - t0 < DURATION:
        el = time.time() - t0
        p = procs()
        if not p["pythonw"]:
            print(f"\n[{datetime.now():%H:%M:%S} +{el:.0f}s] *** pythonw 消失 —— ok-ww 退出 ***")
            return 0

        wins = C.find_okww_window()
        if not wins:
            time.sleep(3)
            continue
        hwnd, pid, title = wins[0]

        # 强制前台并验证
        if user32.GetForegroundWindow() != hwnd:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.6)
        fg_ok = user32.GetForegroundWindow() == hwnd

        r = C.get_window_rect(hwnd)
        w, h = r.right - r.left, r.bottom - r.top
        got = C.capture_region(r.left, r.top, w, h)
        if got is None:
            time.sleep(3)
            continue
        d, fw, fh = got
        f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

        # 身份校验：侧栏图标必须在 (16,215) 附近
        sc, mx, my = match_template(f, side)
        identity_ok = sc > 0.95 and abs(mx - 16) < 12

        if not identity_ok:
            bad_frames += 1
            print(f"[{datetime.now():%H:%M:%S} +{el:5.0f}s] [!] 身份校验失败 "
                  f"(侧栏 score={sc:.3f} pos=({mx},{my})) 前台={fg_ok} —— 本帧作废")
            time.sleep(3)
            continue

        # 面板区域亮度
        top = f[60:130]
        bright = float((top.astype(np.float32).mean(axis=2) > 100).mean())
        fp = int(f[::40, ::40].astype(np.float32).mean())

        sig = (w, h, round(bright, 3), fp)
        if sig != last:
            last = sig
            print(f"[{datetime.now():%H:%M:%S} +{el:5.0f}s] {w}x{h} 面板={bright:.3f} "
                  f"指纹={fp} pythonw={len(p['pythonw'])} game={len(p['Client-Win64-Shipping'])}")
            Image.fromarray(f).save(OUT / f"obs-{n_saved:03d}.png")
            n_saved += 1

        time.sleep(3)

    print(f"\n[{datetime.now():%H:%M:%S}] 超时 {DURATION}s；作废帧 {bad_frames}；有效快照 {n_saved}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
