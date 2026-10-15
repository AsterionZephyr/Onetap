import os, sys
import numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import assets as A, match
from PIL import Image

reg = A.Registry()
t = reg["daily_row"].load()
for tag, p in [("running-000", r"probe\running-000.png"),
               ("obs-000", r"probe\obs-000.png")]:
    f = np.asarray(Image.open(p).convert("RGB"))
    h, w = f.shape[:2]
    print(f"\n=== {tag} {w}x{h} : 全帧找最像整行模板的位置 ===")
    res = match.match_best(f, t)
    print("  整行 match_best:", None if res is None else f"{res[0]:.4f}@({res[1]},{res[2]})")
    # 用「每日任务」四字切片（x=49..78）当探针，看它在帧里落在哪
    four = t[:, 49:78]
    print("  四字切片 shape", four.shape)
    sm = match.score_map(f, four)
    hits = match.local_maxima(sm, 0.80, min_dist=30)
    print("  四字>=0.80 候选:", [f"{s:.4f}@({x},{y})" for y,x,s in hits[:8]])
    # 日历图标切片
    cal = t[:, 17:32]
    sm2 = match.score_map(f, cal)
    hits2 = match.local_maxima(sm2, 0.80, min_dist=30)
    print("  日历>=0.80 候选:", [f"{s:.4f}@({x},{y})" for y,x,s in hits2[:8]])
