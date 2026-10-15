import os, sys
import numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import match
from PIL import Image

f = np.asarray(Image.open(r"probe\running-000.png").convert("RGB"))
h, w = f.shape[:2]
g = match.to_gray(f)
br = g > 140

# 缩略图 y≈461/625 => 原图 y≈922。全宽扫，看亮像素落在哪些 x
print("=== 原帧 y=915..935 全宽亮像素列（只列出有亮像素的 x）===")
cols = [x for x in range(w) if br[915:935, x].sum() > 0]
if cols:
    # 压缩成连续段
    segs, s = [], cols[0]
    for a, b in zip(cols, cols[1:]):
        if b - a > 4:
            segs.append((s, a)); s = b
    segs.append((s, cols[-1]))
    for s0, s1 in segs:
        print(f"   x={s0:4d}..{s1:4d}  (宽 {s1-s0+1})")
print("\n=== 同一 y 带内，亮像素总数 =", int(br[915:935, :].sum()))

# 换几个 y 带试探行的真实位置
print("\n=== 逐 y 扫描：x=0..200 内亮像素计数 > 0 的 y ===")
ys = [y for y in range(600, 1100) if br[y, 0:200].sum() > 0]
print("   ", ys[:60])
