"""anchor_ambiguity.py — 检查日历图标是否为歧义锚点（正确版）

用户指出：进度面板日志行 "已完成: 📅 每日任务 已运行: ..." 里也有日历图标，
与 2_ww.png 的日历图标相同，可能抢走匹配，导致「开始」点击落空。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")


def score_map(frame, tpl):
    fh, fw, _ = frame.shape
    th, tw, _ = tpl.shape
    f = frame.astype(np.float32).mean(axis=2)
    t = tpl.astype(np.float32).mean(axis=2)
    tc = t - t.mean()
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


frame = np.array(Image.open(OUT / "obs-000.png").convert("RGB"))
fh, fw, _ = frame.shape
print(f"帧 {fw}x{fh}")

tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))

for label, sub in [("日历图标", tpl[:, 9:26]),
                   ("日历+每日", tpl[:, 9:45]),
                   ("每日任务四字", tpl[:, 35:72])]:
    th, tw, _ = sub.shape
    sm = score_map(frame, sub)
    print(f"\n{'='*66}")
    print(f"[{label}] {tw}x{th}   最高分={sm.max():.4f}")
    print(f"{'='*66}")

    order = np.dstack(np.unravel_index(np.argsort(-sm, axis=None), sm.shape))[0]
    hits = []
    for yx in order:
        y, x = int(yx[0]), int(yx[1])
        if sm[y, x] < 0.85:
            break
        if all(abs(y - h[0]) > 12 or abs(x - h[1]) > 12 for h in hits):
            hits.append((y, x, float(sm[y, x])))

    print(f"  score>=0.85 的位置共 {len(hits)} 个：")
    for i, (y, x, s) in enumerate(hits[:10]):
        note = ""
        if y < 200:
            note = "  (顶部区域)"
        print(f"    [{i}] score={s:.4f}  窗口内=({x},{y}){note}")

    if hits:
        for i, (y, x, s) in enumerate(hits[:2]):
            c = frame[max(0, y - 6):y + th + 6, max(0, x - 6):x + tw + 40]
            Image.fromarray(c).save(OUT / f"amb-{label}-{i}.png")
        print(f"    落盘 amb-{label}-0.png / amb-{label}-1.png")

print(f"\n{'='*66}")
print("判定")
print(f"{'='*66}")
print("若是『日历图标』单独作锚点且存在多个 >=0.95 的位置 -> 歧义锚点，")
print("匹配器可能选错那一个，点击随即落空。")
print("对策：锚点必须包含**足够长且唯一**的文字（如『每日任务』四个字），")
print("      并在命中后再做一次**唯一性检查**（高分位置是否只有一个）。")
