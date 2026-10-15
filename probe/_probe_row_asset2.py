import os, sys
import numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import assets as A, match
from PIL import Image

reg = A.Registry()
t = reg["daily_row"].load()
print("2_ww.png shape =", t.shape, " born_size(登记) =", reg["daily_row"].born_size)

# 2_ww.png 自己就是某尺寸下的整行；查它内部的「每日任务」四字与日历图标在哪
g = match.to_gray(t)
print("\n[2_ww.png 行内亮像素分布 x<120]")
br = g > 140
for x in range(0, 120):
    col = int(br[:, x].sum())
    if col:
        print(f"   x={x:3d} 亮像素={col}")
