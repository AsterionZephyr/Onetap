"""observe_running.py — 观测正在运行的 ok-ww 任务（只读）

当前状态（用户提供的画面）：
  - 每日任务 已运行 1m32s
  - current task = wait main esc=True
  - 日志 = claim daily reward via coordinate
  - 错误 = 请在大世界并在队伍中开始！

本脚本周期性记录：
  1. 进度面板上的运行时长（说明任务是否还在推进）
  2. ok-ww 进程/窗口是否消失
  3. 面板是否变为"已完成"
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
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 600


def procs():
    d = {}
    for n in ["pythonw", "ok-ww", "Client-Win64-Shipping"]:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        d[n] = [l.split('","')[1] for l in o.splitlines() if l.startswith('"')]
    return d


def grab(hwnd, r):
    w, h = r.right - r.left, r.bottom - r.top
    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        return None
    d, fw, fh = got
    return np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]


def main():
    print("=" * 74)
    print("观测：正在运行的 ok-ww 任务")
    print("=" * 74)
    t0 = time.time()
    last_sig = None
    frame_i = 0

    while time.time() - t0 < DURATION:
        el = time.time() - t0
        p = procs()
        wins = C.find_okww_window()

        if not p["pythonw"]:
            print(f"\n[{datetime.now():%H:%M:%S} +{el:.0f}s] *** pythonw 消失 —— ok-ww 已退出 ***")
            print(f"    ok-ww={len(p['ok-ww'])} game={len(p['Client-Win64-Shipping'])}")
            return 0

        if not wins:
            print(f"\n[{datetime.now():%H:%M:%S} +{el:.0f}s] 窗口消失但进程还在")
            time.sleep(3)
            continue

        hwnd, pid, title = wins[0]
        r = C.get_window_rect(hwnd)
        w, h = r.right - r.left, r.bottom - r.top
        f = grab(hwnd, r)
        if f is None:
            time.sleep(3)
            continue

        # 面板区域（顶部 60..120）亮度：判断面板是否存在
        top = f[60:130]
        bright = (top.astype(np.float32).mean(axis=2) > 100).mean()
        # 全帧指纹（粗），用于检测画面变化
        fp = int(f[::40, ::40].astype(np.float32).mean())

        sig = (len(p["pythonw"]), w, h, round(bright, 3), fp)
        if sig != last_sig:
            last_sig = sig
            print(f"[{datetime.now():%H:%M:%S} +{el:5.0f}s] "
                  f"{w}x{h}  面板亮度={bright:.3f}  指纹={fp}  "
                  f"pythonw={len(p['pythonw'])} game={len(p['Client-Win64-Shipping'])}")
            Image.fromarray(f).save(OUT / f"running-{frame_i:03d}.png")
            frame_i += 1
            if frame_i > 40:
                frame_i = 0

        time.sleep(3)

    print(f"\n[{datetime.now():%H:%M:%S}] 观测超时 {DURATION}s，ok-ww 仍在运行")
    return 2


if __name__ == "__main__":
    sys.exit(main())
