import sys, numpy as np
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import match
from PIL import Image
p = r"E:\TOOLS\ScriptsGames\Onetap\logs\runs\run-20261015-200219\shots\001-first-frame.png"
rgb = np.asarray(Image.open(p).convert("RGB"))
print("帧:", rgb.shape)
g = match.to_gray(rgb[:160, :100])
print("左上 160x100 灰度：min=%d max=%d mean=%.1f" % (g.min(), g.max(), g.mean()))
# 找亮线
for y in range(160):
    xs = np.where(g[y] > 140)[0]
    if len(xs) >= 6:
        print(f"   y={y:3d} 亮像素={len(xs)} x={xs[0]}..{xs[-1]}")
print("\nfind_menu_glyph ->", match.find_menu_glyph(rgb))
