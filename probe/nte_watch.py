"""nte_watch.py — 观测 ok-nte 任务：完成判定 + 是否自动退出

与 ok-ww 的观测一致，但按 ok-nte 的界面特征判定：
  - 运行中：底部出现「暂停」「停止」按钮
  - 已停止：底部回到「开始」按钮
  - 自动退出：pythonw 消失

带身份校验：每轮确认「日常任务」文字锚点仍在（否则帧可能来自其他窗口）。
"""

import sys
import time
import ctypes
import subprocess
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template
from nte_main import find_nte_layer2, R

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 1800


def pids(name):
    o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe",
                        "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, errors="replace").stdout
    return [l.split('","')[1] for l in o.splitlines() if l.startswith('"')]


def main():
    print("=" * 74)
    print("观测 ok-nte 任务：完成判定 / 自动退出")
    print("=" * 74)
    a_daily = np.array(Image.open(TPL / "3_nte_daily.png").convert("RGB"))
    a_start = np.array(Image.open(TPL / "2_nte.png").convert("RGB"))

    t0 = time.time()
    last = None
    saved = 0
    while time.time() - t0 < DURATION:
        el = time.time() - t0
        pw = pids("pythonw")
        if not pw:
            print(f"\n[{datetime.now():%H:%M:%S} +{el:.0f}s] *** pythonw 消失 —— ok-nte 已退出 ***")
            print(f"    ok-nte.exe={pids('ok-nte')}")
            return 0

        ws = [x for x in find_nte_layer2() if x[4] > 200 and x[6]]
        if not ws:
            time.sleep(3)
            continue
        hwnd = ws[0][0]
        if user32.GetForegroundWindow() != hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.4)
        r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.r - r.l, r.b - r.t
        got = C.capture_region(r.l, r.t, w, h)
        if not got:
            time.sleep(3)
            continue
        d, fw, fh = got
        f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

        # 身份校验
        s_id, x_id, y_id = match_template(f, a_daily)
        if s_id < 0.9:
            print(f"[{datetime.now():%H:%M:%S} +{el:5.0f}s] [!] 身份校验失败 "
                  f"(日常任务 score={s_id:.3f}) 帧作废")
            time.sleep(3)
            continue

        # 状态：开始按钮是否还在
        s_start, _, _ = match_template(f, a_start)
        state = "运行中" if s_start < 0.9 else "空闲"
        fp = int(f[::40, ::40].astype(np.float32).mean())

        sig = (state, round(s_start, 3), fp)
        if sig != last:
            last = sig
            print(f"[{datetime.now():%H:%M:%S} +{el:5.0f}s] {w}x{h} "
                  f"状态={state} 开始按钮score={s_start:.3f} 指纹={fp}")
            Image.fromarray(f).save(OUT / f"ntewatch-{saved:03d}.png")
            saved += 1

        time.sleep(4)

    print(f"\n[{datetime.now():%H:%M:%S}] 超时 {DURATION}s；ok-nte 仍在运行")
    return 2


if __name__ == "__main__":
    sys.exit(main())
