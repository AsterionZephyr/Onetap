"""locate_start.py — 定位「每日任务」行末端的「开始」按钮（只读，不点击）

方法：
  1. 用 2_ww.png 的**文字部分**精确定位该行（score 应=1.0）
  2. 由模板内「开始」按钮相对文字起点 的偏移，推算按钮在本帧中的位置
  3. 交叉验证：在推算位置附近真实存在高亮按钮块
  4. 输出窗口内坐标与屏幕坐标
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
    print("定位「每日任务」行的「开始」按钮")
    print("=" * 66)
    print(f"ok-ww {w}x{h} @ ({r.left},{r.top})   前台={fg == hwnd}")

    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape

    # --- 模板内：文字段 与 按钮段 的横向范围 ---
    tg = tpl.astype(np.float32).mean(axis=2)
    colmax = tg.max(axis=0)
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

    text_run = runs[0]                       # 日历+每日任务
    btn_run = max(runs, key=lambda rr: rr[1] - rr[0])   # 最宽的一段 = 开始按钮
    print(f"\n模板内：文字段={text_run}  按钮段={btn_run}")
    btn_cx_in_tpl = (btn_run[0] + btn_run[1]) // 2
    text_x0 = text_run[0]
    print(f"  按钮中心相对模板左缘 = {btn_cx_in_tpl}")
    print(f"  文字起点相对模板左缘 = {text_x0}")
    print(f"  按钮相对文字的偏移   = {btn_cx_in_tpl - text_x0}")

    # --- 用文字段匹配定位该行 ---
    tx0, tx1 = text_run
    tx1 = min(tw - 1, tx0 + 97)              # 取与上次相同的 97 宽
    sub = tpl[:, tx0:tx1 + 1]
    sh, sw, _ = sub.shape
    sc, mx, my = match_template(frame, sub)
    print(f"\n[文字段匹配] score={sc:.4f}  pos=({mx},{my})  （模板文字宽 {sw}）")
    if sc < 0.95:
        print("  [NG] 分数过低，拒绝据此推算坐标")
        return 1
    text_frame_x0 = mx - tx0                 # 换算：模板左缘在帧中的 x
    print(f"  => 模板左缘对齐到帧 x = {text_frame_x0}")
    print(f"  => 模板覆盖帧范围 x = {text_frame_x0} .. {text_frame_x0 + tw - 1}")

    # --- 推算按钮位置 ---
    pred_cx = text_frame_x0 + btn_cx_in_tpl
    pred_cy = my + th // 2
    print(f"\n[推算] 按钮中心（窗口内分量）≈ ({pred_cx},{pred_cy})")

    # --- 交叉验证：该处是否真的是高亮按钮 ---
    g = frame.astype(np.float32).mean(axis=2)
    win = 40
    x0v, x1v = max(0, pred_cx - win), min(fw, pred_cx + win)
    y0v, y1v = max(0, pred_cy - 18), min(fh, pred_cy + 18)
    patch = g[y0v:y1v, x0v:x1v]
    brightfrac = float((patch > 200).mean())
    print(f"[交叉验证] 推算位置周围 {x1v-x0v}x{y1v-y0v} 内亮像素占比 = {brightfrac:.3f}")
    if brightfrac > 0.25:
        print("  [OK] 确实是高亮按钮块")
    else:
        print("  [!!] 该处不像白色按钮，需人工确认")

    # 精修：在推算位置附近找真实亮块中心
    near = g[max(0, pred_cy - 25):pred_cy + 25, max(0, pred_cx - 120):pred_cx + 120]
    bm = near > 200
    if bm.sum() > 100:
        cols = np.where(bm.sum(axis=0) > 3)[0]
        rows = np.where(bm.sum(axis=1) > 3)[0]
        if len(cols) and len(rows):
            real_cx = max(0, pred_cx - 120) + (cols.min() + cols.max()) // 2
            real_cy = max(0, pred_cy - 25) + (rows.min() + rows.max()) // 2
            print(f"[精修] 实际亮块中心（窗口内）= ({real_cx},{real_cy})")
            print(f"       实际亮块范围 x={max(0,pred_cx-120)+cols.min()}..{max(0,pred_cx-120)+cols.max()}"
                  f"  y={max(0,pred_cy-25)+rows.min()}..{max(0,pred_cy-25)+rows.max()}")
            pred_cx, pred_cy = real_cx, real_cy

    # 裁图供肉眼确认
    pad = 20
    crop = frame[max(0, pred_cy - pad - 10):pred_cy + pad + 10,
                 max(0, pred_cx - 90):pred_cx + 60]
    Image.fromarray(crop).save(OUT / "start-button-area.png")
    print(f"\n落盘 start-button-area.png {crop.shape[1]}x{crop.shape[0]}")

    sx, sy = r.left + pred_cx, r.top + pred_cy
    print(f"\n{'='*66}")
    print(f"「开始」按钮  窗口内坐标 = ({pred_cx},{pred_cy})")
    print(f"             屏幕坐标   = ({sx},{sy})")
    print(f"{'='*66}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
