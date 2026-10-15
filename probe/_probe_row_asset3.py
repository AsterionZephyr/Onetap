import os, sys
import numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import assets as A, match
from PIL import Image

reg = A.Registry()
t = reg["daily_row"].load()
f = np.asarray(Image.open(r"probe\running-000.png").convert("RGB"))

# 在真实帧里定位「每日任务」行：用整行模板的粗匹配已知在 y=844 附近
# 直接在真实帧扫 y=820..880 区域的亮像素，找行内结构
print("真实帧 1875x1250  y=820..880 的亮像素列分布（x<120）")
g = match.to_gray(f)
br = g > 140
for x in range(0, 120):
    col = int(br[820:880, x].sum())
    if col:
        print(f"   x={x:3d} 亮像素={col}")
