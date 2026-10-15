"""check_anchor_collision.py — 检查「日历图标」是否出现在多处（导致锚点误判）

用户指出：日志行 "已完成: 📅 每日任务 已运行: 0h 1m 32s" 里也有日历图标，
与 2_ww.png 的日历图标相同，可能抢走了匹配。

本脚本：
  1. 在整帧里找出所有「日历图标」的匹配位置（不取最佳，取**全部高分位置**）
  2. 对比它们的分数与坐标
  3. 判断锚点是否可能落到了错误的那一个
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


def score_map(frame, tpl):
    """返回全帧逐点相关分数矩阵（用于找所有局部极大）。"""
    fh, fw, _ = frame.shape
    th, tw, _ = tpl.shape
    f = frame.astype(np.float32).mean(axis=2)
    t = tpl.astype(np.float32).mean(axis=2)
    tc = t - t.mean()
    tn = np.sqrt((tc ** 2).sum())
    if tn == 0:
        return None
    out = np.full((fh - th + 1, fw - tw + 1), -2.0, dtype=np.float32)
    for y in range(0, fh - th + 1):
        row = f[y:y + th]
        for x in range(0, fw - tw + 1):
            win = row[:, x:x + tw]
            wc = win - win.mean()
            wn = np.sqrt((wc ** 2).sum())
            if wn:
                out[y, x] = float((wc * tc).sum() / (wn * tn))
    return out


def local_maxima(sm, thresh, min_dist=15):
    hits = []
    h, w = sm.shape
    order = np.dstack(np.unravel_index(np.argsort(-sm, axis=None), sm.shape))[0]
    for y, x in order:
        if sm[y, x] < thresh:
            break
        if all(abs(y - yy) > min_dist or abs(x - xx) > min_dist for yy, xx in hits):
            hits.append((int(y), int(x), float(sm[y, x])))
    return hits


def main():
    wins = C.find_okww_window()
    hwnd, pid, title = wins[0]
    C.user32.SetForegroundWindow(hwnd)
    import time
    time.sleep(0.6)
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    print(f"窗口 {w}x{h}   前台={C.user32.GetForegroundWindow()==hwnd}")

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))

    tests = [
        ("日历图标 (9..26)", tpl[:, 9:26]),
        ("日历+每日 (9..45)", tpl[:, 9:45]),
        ("每日任务四字 (35..72)", tpl[:, 35:72]),
        ("文字段 (9..107)", tpl[:, 9:107]),
    ]

    for name, sub in tests:
        sh, sw, _ = sub.shape
        print(f"\n{'='*68}")
        print(f"[{name}]  尺寸 {sw}x{sh}  —— 全帧所有高分位置")
        print(f"{'='*68}")
        sm = score_map(frame, sub)
        if sm is None:
            print("  无法计算")
            continue
        top = float(sm.max())
        hits = local_maxima(sm, max(0.80, top - 0.12), min_dist=max(12, sw // 2))
        print(f"   最高分 = {top:.4f}")
        for i, (y, x, s) in enumerate(hits[:8]):
            tag = ""
            if i == 0:
                tag = "  <-- 匹配器会选这个"
            print(f"   [{i}] score={s:.4f}  窗口内=({x},{y}){tag}")

        # 落盘最高分处与次高分处的裁图
        if hits:
            y, x, s = hits[0]
            c = frame[max(0, y - 8):y + sh + 8, max(0, x - 8):x + sw + 8]
            Image.fromarray(c).save(OUT / f"anchor-{name.split()[0]}-top.png")
            if len(hits) > 1:
                y2, x2, s2 = hits[1]
                c2 = frame[max(0, y2 - 8):y2 + sh + 8, max(0, x2 - 8):x2 + sw + 8]
                Image.fromarray(c2).save(OUT / f"anchor-{name.split()[0]}-2nd.png")
                print(f"   => 落盘 top / 2nd 裁图（若二者内容相同，说明锚点有歧义）")

    print(f"\n{'='*68}")
    print("结论要点")
    print(f"{'='*68}")
    print("若『日历图标』在全帧有多个 >0.9 的位置，则它是**歧义锚点**：")
    print("  进度面板里的日历图标与任务行的日历图标相同，匹配器无法区分。")
    print("  这会使『每日任务』行定位错误 -> 点击落空。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
