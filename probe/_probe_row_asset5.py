import os, sys
import numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import assets as A, match
from PIL import Image

reg = A.Registry()
t = reg["daily_row"].load()
f = np.asarray(Image.open(r"probe\running-000.png").convert("RGB"))
h, w = f.shape[:2]
print(f"帧 {w}x{h}  模板 2_ww.png {t.shape[1]}x{t.shape[0]}")

# 「每日任务」行在缩略图 y≈461/625 -> 原图 y≈922
g = match.to_gray(f)
br = g > 140
for y0 in (900, 910):
    print(f"\n--- 原帧 y={y0}..{y0+50} 亮像素列分布 (x<130) ---")
    out = []
    for x in range(0, 130):
        c = int(br[y0:y0+50, x].sum())
        if c:
            out.append(f"{x}:{c}")
    print("   " + "  ".join(out))

# 模板内部同样的分布，做对照
print("\n--- 模板 2_ww.png 亮像素列分布 (x<130) ---")
bt = match.to_gray(t) > 140
out = []
for x in range(0, 130):
    c = int(bt[:, x].sum())
    if c:
        out.append(f"{x}:{c}")
print("   " + "  ".join(out))
