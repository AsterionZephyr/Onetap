"""match_2ww_now.py — 在 1875x1250 窗口下定位 2_ww.png（只读）

用户确认「每日任务」行就在本页最顶端。
本脚本：
  1. 抓当前帧
  2. 用 2_ww.png 做多尺度匹配，找出它对应的尺度（=> 反推出生尺寸）
  3. 落盘匹配区域，肉眼核对
  4. 计算「开始」按钮的屏幕坐标（供后续点击）
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
    if not wins:
        print("[NG] 未找到 ok-ww")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    fg = C.user32.GetForegroundWindow()
    print("=" * 66)
    print("在 2_ww 目标页定位模板")
    print("=" * 66)
    print(f"ok-ww {w}x{h} @ ({r.left},{r.top})   前台={fg == hwnd}")

    got = C.capture_region(r.left, r.top, w, h)
    if got is None:
        print("[NG] 抓帧失败")
        return 1
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(frame).save(OUT / "page-tasks.png")

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape
    print(f"\n2_ww.png 原始 {tw}x{th}")
    print(f"窗口宽 {fw}，模板宽 {tw}，模板/窗口 = {tw/fw:.4f}")

    # --- 多尺度匹配 ---
    print("\n[多尺度匹配]")
    best = None
    results = []
    for scale in [x / 100 for x in range(50, 135, 5)]:
        nw, nh = int(tw * scale), int(th * scale)
        if nw < 20 or nh < 8 or nw > fw or nh > fh:
            continue
        rs = np.array(Image.fromarray(tpl).resize((nw, nh), Image.LANCZOS))
        res = match_template(frame, rs)
        if res is None:
            continue
        sc, mx, my = res
        results.append((sc, scale, nw, nh, mx, my))
        if best is None or sc > best[0]:
            best = (sc, scale, nw, nh, mx, my)

    for sc, scale, nw, nh, mx, my in sorted(results, key=lambda t: -t[0])[:6]:
        print(f"   scale={scale:.2f}  {nw}x{nh}  score={sc:.4f}  pos=({mx},{my})")

    if best is None:
        print("\n[NG] 无任何尺度可匹配")
        return 1

    sc, scale, nw, nh, mx, my = best
    print(f"\n[最佳] scale={scale:.2f}  尺寸={nw}x{nh}  score={sc:.4f}  pos=({mx},{my})")

    # 裁出匹配区域
    pad = 8
    crop = frame[max(0, my - pad):my + nh + pad, max(0, mx - pad):mx + nw + pad]
    Image.fromarray(crop).save(OUT / "match2-region.png")
    print(f"落盘 match2-region.png  {crop.shape[1]}x{crop.shape[0]}")

    if sc > 0.85:
        print("=> 高度可信")
    elif sc > 0.6:
        print("=> 中等，需肉眼确认")
    else:
        print("=> 不可信")

    # 反推出生尺寸
    if abs(scale - 1.0) > 0.03:
        implied = nw / scale if scale else 0
        print(f"\n[INV-4 推断] 模板在 {scale:.2f} 倍时可匹配")
        print(f"   模板原始宽 {tw}，可用宽 {nw}")
        print(f"   若当时窗口宽 = {tw} / (可用窗口宽 {fw} 的占比) ...")
        print(f"   模板宽 {tw} vs 已匹配宽度 {nw} => 原始窗口可能是 {tw * (fw / nw):.0f} 宽")

    # 「开始」按钮坐标：模板右侧的白色按钮
    # 在匹配区域内找最亮的大块
    sub = frame[my:my + nh, mx:mx + nw]
    g = sub.astype(np.float32).mean(axis=2)
    bright = g > 200
    cols = np.where(bright.sum(axis=0) > nh * 0.3)[0]
    if len(cols):
        bx0, bx1 = cols.min(), cols.max()
        bcx = mx + (bx0 + bx1) // 2
        bcy = my + nh // 2
        print(f"\n[开始按钮] 匹配区内的亮块 x={bx0}..{bx1}（相对）")
        print(f"   按钮中心 窗口内=({bcx},{bcy})")
        print(f"   屏幕坐标=({r.left + bcx},{r.top + bcy})")
    else:
        print("\n[开始按钮] 未在匹配区内找到高亮按钮块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
