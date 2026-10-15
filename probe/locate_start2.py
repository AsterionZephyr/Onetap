"""locate_start2.py — 按"行结构"定位「开始」按钮（只读）

修正上一版的错误：按钮是**右对齐**到行的，不由模板偏移决定。
正确做法：
  1. 用文字段精确定位「每日任务」行 -> 得到该行的 y 与左侧 x
  2. 在同一 y 上，向右扫描，找出该行的高亮按钮块
  3. 交叉验证按钮确实在同一行
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
    fg = C.user32.GetForegroundWindow()
    print("=" * 66)
    print("定位「开始」按钮（按行结构，右对齐）")
    print("=" * 66)
    print(f"ok-ww {w}x{h} @ ({r.left},{r.top})   前台={fg == hwnd}")

    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape

    # 1) 文字段定位行
    sub = tpl[:, 9:9 + 98]
    sc, mx, my = match_template(frame, sub)
    row_cy = my + th // 2
    print(f"\n[1] 文字段匹配 score={sc:.4f} pos=({mx},{my})")
    print(f"    => 该行中心 y = {row_cy}  （模板高 {th}）")
    if sc < 0.95:
        print("  [NG] 匹配分数不足")
        return 1

    # 2) 在同一 y 带上向右扫描高亮按钮
    band_y0, band_y1 = max(0, my - 5), min(fh, my + th + 5)
    band = frame[band_y0:band_y1]
    g = band.astype(np.float32).mean(axis=2)
    bright = g > 200
    colsum = bright.sum(axis=0)
    cols = np.where(colsum > (band_y1 - band_y0) * 0.35)[0]
    print(f"\n[2] 行内高亮列：{len(cols)} 个（y {band_y0}..{band_y1}）")
    if not len(cols):
        print("  [NG] 该行未发现白色按钮块")
        return 1

    # 分组找连续块，取最右侧那个
    groups = []
    s = cols[0]
    prev = cols[0]
    for c in cols[1:]:
        if c - prev > 8:
            groups.append((s, prev))
            s = c
        prev = c
    groups.append((s, prev))
    print(f"    连续块：{groups}")
    bx0, bx1 = groups[-1]
    bcx = (bx0 + bx1) // 2

    # 纵向范围
    sub_b = bright[:, bx0:bx1 + 1]
    rows = np.where(sub_b.sum(axis=1) > 3)[0]
    by0 = band_y0 + rows.min()
    by1 = band_y0 + rows.max()
    bcy = (by0 + by1) // 2
    print(f"    最右亮块 x={bx0}..{bx1} (宽 {bx1-bx0})  y={by0}..{by1} (高 {by1-by0})")
    print(f"    按钮中心（窗口内）= ({bcx},{bcy})")

    # 3) 交叉验证：按钮中心是否落在该行 y 范围内
    if my <= bcy <= my + th:
        print(f"  [OK] 按钮中心 y={bcy} 落在该行 y={my}..{my+th} 内 —— 同一行")
    else:
        print(f"  [!!] 按钮 y={bcy} 不在行范围 {my}..{my+th} 内")

    # 裁图
    crop = frame[max(0, bcy - 30):bcy + 30, max(0, bcx - 100):bcx + 80]
    Image.fromarray(crop).save(OUT / "start-btn-final.png")
    print(f"\n落盘 start-btn-final.png {crop.shape[1]}x{crop.shape[0]}")

    # 整行裁图（从文字到按钮）
    line = frame[max(0, my - 8):my + th + 8, max(0, mx - 15):bx1 + 20]
    Image.fromarray(line).save(OUT / "daily-row.png")
    print(f"落盘 daily-row.png {line.shape[1]}x{line.shape[0]}")

    sx, sy = r.left + bcx, r.top + bcy
    print(f"\n{'='*66}")
    print(f"「开始」按钮  窗口内 = ({bcx},{bcy})")
    print(f"             屏幕坐标 = ({sx},{sy})")
    print(f"  按钮宽 {bx1-bx0}px  高 {by1-by0}px")
    print(f"  提示：点击按钮中心安全；按钮内相对位置 x≈0.5 y≈0.5")
    print(f"{'='*66}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
