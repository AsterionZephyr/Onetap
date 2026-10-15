"""match_by_text.py — 用模板的「文字部分」匹配，避开空行按钮的同构干扰（只读）

洞见：2_ww.png 大部分是空背景 + 右侧按钮，整体匹配不具鉴别力
      （空行 + 开始按钮 也能得 0.85）。
      真正的鉴别特征是左侧的「每日任务」文字与日历图标。
"""

import sys
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
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    print(f"ok-ww {w}x{h} @ ({r.left},{r.top})")

    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape
    print(f"2_ww.png {tw}x{th}")

    # 找模板中「有内容」的横向范围（文字+图标），排除右侧按钮区的干扰
    tg = tpl.astype(np.float32).mean(axis=2)
    colmax = tg.max(axis=0)
    # 判定每列是否有明显亮像素（文字/图标/按钮）
    has = colmax > 120
    runs = []
    s = None
    for x, v in enumerate(has):
        if v and s is None:
            s = x
        elif not v and s is not None:
            if x - s >= 3:
                runs.append((s, x - 1))
            s = None
    if s is not None:
        runs.append((s, len(has) - 1))
    print(f"\n模板内容横段（亮列簇）: {runs}")

    # 取最左侧那一段（应是日历图标 + 每日任务文字）
    if not runs:
        print("[NG] 模板无内容段")
        return 1
    tx0, tx1 = runs[0]
    # 适当向右扩一点以涵盖文字
    tx1 = min(tw - 1, tx0 + int((tx1 - tx0) * 3.5) + 40)
    print(f"取左侧文字段 x={tx0}..{tx1}  （宽 {tx1-tx0+1}）")

    sub = tpl[:, tx0:tx1 + 1]
    Image.fromarray(sub).save(OUT / "tpl-text-part.png")
    print(f"落盘 tpl-text-part.png {sub.shape[1]}x{sub.shape[0]}")

    sh, sw, _ = sub.shape
    print("\n[用文字段匹配]")
    best = None
    for scale in [x / 100 for x in range(50, 135, 5)]:
        nw, nh = int(sw * scale), int(sh * scale)
        if nw < 15 or nw > fw or nh > fh:
            continue
        rs = np.array(Image.fromarray(sub).resize((nw, nh), Image.LANCZOS))
        res = match_template(frame, rs)
        if res is None:
            continue
        sc, mx, my = res
        if best is None or sc > best[0]:
            best = (sc, scale, nw, nh, mx, my)
        if scale in (0.9, 0.95, 1.0, 1.05, 1.1):
            print(f"   scale={scale:.2f} {nw}x{nh} score={sc:.4f} pos=({mx},{my})")

    sc, scale, nw, nh, mx, my = best
    print(f"\n[最佳] scale={scale:.2f} score={sc:.4f} pos=({mx},{my}) 尺寸={nw}x{nh}")
    pad = 6
    crop = frame[max(0, my - pad):my + nh + pad, max(0, mx - pad):mx + nw + pad]
    Image.fromarray(crop).save(OUT / "match-text-region.png")
    print(f"落盘 match-text-region.png {crop.shape[1]}x{crop.shape[0]}")

    # 同时：直接扫描顶部若干行，找含「开始」按钮的行 y
    print("\n[扫描] 各行的高亮按钮块（找所有『开始』按钮的 y）")
    g = frame.astype(np.float32).mean(axis=2)
    bright = g > 210
    rowcnt = bright.sum(axis=1)
    ys = []
    y = 0
    while y < fh:
        if rowcnt[y] > 60:
            y0 = y
            while y < fh and rowcnt[y] > 60:
                y += 1
            ys.append((y0, y - 1))
        y += 1
    for i, (y0, y1) in enumerate(ys[:12]):
        band = bright[y0:y1 + 1]
        cols = np.where(band.any(axis=0))[0]
        print(f"   [{i}] y={y0}..{y1}  x={cols.min()}..{cols.max()}  宽={cols.max()-cols.min()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
