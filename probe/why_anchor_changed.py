"""why_anchor_changed.py — 排查文字段锚点分数从 1.0000 掉到 0.4722 的原因

可能原因：
  A. 窗口当前不在「任务列表页」（页面变了）
  B. 窗口不在前台，抓到的是别的窗口
  C. 列表被滚动了，每日任务行不在原位
  D. ok-ww 刚重启（本次是全新启动的实例），默认页面不同
"""

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")


def main():
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 无 ok-ww 窗口")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    fg = C.user32.GetForegroundWindow()
    print("=" * 68)
    print(f"ok-ww hwnd={hwnd} pid={pid} {w}x{h}")
    print(f"前台={fg}  是ok-ww={fg == hwnd}")
    print(f"iconic={bool(C.user32.IsIconic(hwnd))} visible={bool(C.user32.IsWindowVisible(hwnd))}")

    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(frame).save(OUT / "why-anchor.png")
    st = C.frame_stats(d, fw, fh)
    print(f"抓帧 {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")
    print("落盘 why-anchor.png")

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape

    print("\n[多尺度 + 全帧扫描] 文字段")
    sub = tpl[:, 9:9 + 98]
    for scale in [0.8, 0.9, 1.0, 1.1, 1.2]:
        nw, nh = int(sub.shape[1] * scale), int(sub.shape[0] * scale)
        if nw > fw or nh > fh:
            continue
        rs = np.array(Image.fromarray(sub).resize((nw, nh), Image.LANCZOS))
        sc, mx, my = match_template(frame, rs)
        print(f"   scale={scale:.1f} {nw}x{nh} score={sc:.4f} pos=({mx},{my})")

    # 也试试整行
    print("\n[整行] 2_ww 全模板")
    sc, mx, my = match_template(frame, tpl)
    print(f"   score={sc:.4f} pos=({mx},{my})")

    # 侧栏图标也在吗？用于判断是否还在任务页
    print("\n[侧栏图标 1_ww] 是否仍在原位")
    t1 = np.array(Image.open(TPL / "1_ww.png").convert("RGB"))
    sc1, mx1, my1 = match_template(frame, t1)
    print(f"   score={sc1:.4f} pos=({mx1},{my1})  (此前为 1.0000 @ (16,215))")

    # 顶部 300px 亮度分布，看是否有内容
    g = frame[:300].astype(np.float32).mean(axis=2)
    nz = (g > 60).sum()
    print(f"\n[顶部 300px] 亮像素数 = {nz}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
