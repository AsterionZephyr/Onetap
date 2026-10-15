import os, sys
import numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import assets as A, match
from PIL import Image

reg = A.Registry()
row = reg["daily_row"]
print("daily_row: file=%r born_size=%r path=%r" % (row.file, row.born_size, row.path))
print("  spec keys:", list(row.spec.keys()))
t = row.load()
print("  图像 shape =", t.shape, " anchor x0..x1 =", match.ANCHOR_X0, match.ANCHOR_X1)

for tag, p in [("running-000", r"probe\running-000.png"),
               ("obs-000", r"probe\obs-000.png"),
               ("okww-now", r"probe\okww-now.png")]:
    f = np.asarray(Image.open(p).convert("RGB"))
    anchor = match.crop_anchor(t)
    print(f"\n[{tag}] frame {f.shape[1]}x{f.shape[0]}  anchor {anchor.shape}")
    sm = match.score_map(f, anchor)
    hits = match.local_maxima(sm, match.WARN, min_dist=30)
    print("  anchor>=0.85 候选:", [f"{s:.4f}@({x},{y})" for y,x,s in hits[:6]])
    for nm, tpl in (("anchor", anchor), ("整行", t)):
        r = match.match_best(f, tpl)
        print(f"  match_best {nm}: " + ("None" if r is None else f"{r[0]:.4f}@({r[1]},{r[2]})"))
