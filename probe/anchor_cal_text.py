"""anchor_cal_text.py — 实机检验「日历图标 + 每日任务文字」是否唯一（只读）

背景：HANDOFF §5 与 FRAMEWORK §4.4 声称锚点只取「每日任务」四字（tpl[:, 35:72]）即唯一。
本次实机复核发现该结论**只在进度面板展开时成立**：面板收起后列表显示 11 行，
「多账号每日任务」行里的同样四字拿到 0.9991，高于正确行的 0.9225。

本脚本检验用户提出的替代锚点：日历图标 + 「每日任务」文字。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image

FRAME = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe\nav-after.png")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates\2_ww.png")


def score_map(frame, t):
    fh, fw, _ = frame.shape
    th, tw, _ = t.shape
    f = frame.astype(np.float32).mean(axis=2)
    tt = t.astype(np.float32).mean(axis=2)
    tc = tt - tt.mean()
    tn = np.sqrt((tc ** 2).sum())
    out = np.full((fh - th + 1, fw - tw + 1), -2.0, dtype=np.float32)
    for y in range(fh - th + 1):
        row = f[y:y + th]
        for x in range(fw - tw + 1):
            win = row[:, x:x + tw]
            wc = win - win.mean()
            wn = np.sqrt((wc ** 2).sum())
            if wn:
                out[y, x] = float((wc * tc).sum() / (wn * tn))
    return out


def local_maxima(sm, thresh=0.85, min_dist=30):
    order = np.dstack(np.unravel_index(np.argsort(-sm, axis=None), sm.shape))[0]
    out = []
    for yx in order:
        y, x = int(yx[0]), int(yx[1])
        if sm[y, x] < thresh:
            break
        if all(abs(y - yy) > min_dist or abs(x - xx) > min_dist
               for yy, xx, _ in out):
            out.append((y, x, float(sm[y, x])))
    return out


def main():
    im = np.array(Image.open(FRAME).convert("RGB"))
    tpl = np.array(Image.open(TPL).convert("RGB"))
    print(f"帧 {im.shape[1]}x{im.shape[0]}   模板 {tpl.shape[1]}x{tpl.shape[0]}")
    print(f"{'锚点候选':<34}{'宽':>4}{'候选数':>7}   高分位置")
    print("-" * 84)

    cands = [
        ("日历图标 (9..26)", tpl[:, 9:26]),
        ("每日任务四字 (35..72)", tpl[:, 35:72]),
        ("日历+每日任务 (9..72)", tpl[:, 9:72]),
        ("日历+每日 (9..45)", tpl[:, 9:45]),
        ("去掉日历左缘 (30..72)", tpl[:, 30:72]),
    ]
    for name, t in cands:
        sm = score_map(im, t)
        h = local_maxima(sm)
        tag = "  <== 唯一" if len(h) == 1 else ""
        print(f"{name:<34}{t.shape[1]:>4}{len(h):>7}   "
              + "  ".join(f"{s:.4f}@({x},{y})" for y, x, s in h[:6]) + tag)


if __name__ == "__main__":
    main()
