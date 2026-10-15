"""diag_2ww.py — 诊断 2_ww.png 的真实来源（只读）

用户称该模板是在 1500x1000 窗口下截的，但文件宽 1366。
本脚本用三种独立方式判断它究竟来自哪种坐标系。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image

import capture as C
from template_probe import capture_okww, match_template, TPL_DIR, OUT_DIR


def main():
    hwnd, pid, title, r, fw, fh, frame = capture_okww()
    print("=" * 66)
    print("诊断 2_ww.png 的来源")
    print("=" * 66)
    print(f"当前 ok-ww 窗口 = {fw} x {fh}   位置=({r.left},{r.top})")

    p = TPL_DIR / "2_ww.png"
    tpl = Image.open(p)
    t = np.array(tpl.convert("RGB"))
    th, tw, _ = t.shape
    print(f"\n2_ww.png 原始属性：尺寸 {tpl.size}  模式 {tpl.mode}")
    print(f"  像素矩阵 {tw} x {th}")

    print(f"\n[假设检验]")
    print(f"  窗口高 {fh}，模板高 {th}")
    print(f"  窗口宽 {fw}，模板宽 {tw}")
    print(f"  比率 模板/窗口 = {tw/fw:.4f} x {th/fh:.4f}")
    for scale, label in [(1.25, "1.25x"), (1.0, "1.0x"), (1.5, "1.5x")]:
        print(f"  若模板来自 {label} 缩放的截图：1366/{scale:.2f} = {1366/scale:.1f}")

    # --- 方式一：在整帧里做多尺度匹配 ---
    print(f"\n[方式一] 多尺度匹配：把模板缩放到不同宽度再匹配")
    best_overall = None
    for scale in [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25]:
        nw, nh = int(tw * scale), int(th * scale)
        if nw > fw or nh > fh or nw < 10:
            continue
        resized = np.array(Image.fromarray(t).resize((nw, nh), Image.LANCZOS))
        res = match_template(frame, resized)
        if res is None:
            continue
        score, mx, my = res
        mark = ""
        if best_overall is None or score > best_overall[0]:
            best_overall = (score, mx, my, scale, nw, nh)
            mark = "  <-- 目前最佳"
        print(f"   scale={scale:.2f}  尺寸 {nw}x{nh}  score={score:.4f}  pos=({mx},{my}){mark}")

    # --- 方式二：在模板"应出现"的 y 区域找它的真实宽度 ---
    print(f"\n[方式二] 在帧内定位「开始」按钮与「每日任务」文字的实际横向范围")
    # 模板右侧是白色的「开始」按钮。用高亮像素定位。
    gray = frame.astype(np.float32).mean(axis=2)
    # 找亮色（按钮底色接近白 240+）
    bright = gray > 200
    rows = np.where(bright.sum(axis=1) > 20)[0]
    if len(rows):
        print(f"   帧中亮像素行范围：{rows.min()} .. {rows.max()}")
        # 聚焦到下半部分（任务列表通常在窗口下部）
        low = rows[rows > fh * 0.5]
        if len(low):
            y0, y1 = low.min(), low.max()
            band = bright[y0:y1 + 1]
            cols = np.where(band.sum(axis=0) > 0)[0]
            print(f"   下半部亮区 y={y0}..{y1}  x={cols.min()}..{cols.max()}")
    else:
        print("   未发现高亮区域")

    # --- 方式三：直接在帧里找「开始」按钮所在行，量出该行内容宽度 ---
    print(f"\n[方式三] 逐行扫描：找出与模板内容特征最接近的横向条带")
    # 模板底部有一整条浅色按钮。用它做特征。
    if th >= 5:
        tpl_bright_ratio = (t.mean(axis=2) > 200).mean()
        print(f"   模板高亮像素占比 = {tpl_bright_ratio:.4f}")
    best_band = None
    for y in range(0, fh - th + 1, 2):
        band = frame[y:y + th]
        ratio = (band.mean(axis=2) > 200).mean()
        if best_band is None or abs(ratio - tpl_bright_ratio) < abs(best_band[0] - tpl_bright_ratio):
            best_band = (ratio, y)
    if best_band:
        print(f"   最相似条带 y={best_band[1]}  高亮占比={best_band[0]:.4f}")

    # --- 落盘对比图 ---
    print(f"\n[落盘]")
    side = np.zeros((max(th, 120), tw + 60 + 400, 3), dtype=np.uint8)
    side[:th, :tw] = t
    outp = OUT_DIR / "diag-2ww-side.png"
    Image.fromarray(side).save(outp)
    print(f"   {outp.name}（左=模板原文）")

    if best_overall:
        score, mx, my, scale, nw, nh = best_overall
        print(f"\n[结论] 最佳匹配 scale={scale:.2f}  尺寸 {nw}x{nh}  score={score:.4f}  pos=({mx},{my})")
        print(f"   => 模板原始宽度 {tw}，在帧中最匹配时宽度为 {nw}")
        if abs(nw - tw) > 3:
            print(f"   => 模板与当前帧**不同源**，需缩放 {scale:.2f} 才对齐")
        else:
            print(f"   => 模板与当前帧同源")


if __name__ == "__main__":
    main()
