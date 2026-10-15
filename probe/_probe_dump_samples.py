import numpy as np
from PIL import Image
# 把三张样本帧缩到可读尺寸存盘，人眼确认画面里有没有「每日任务」行
for tag, p in [("running-000", r"probe\running-000.png"),
               ("obs-000", r"probe\obs-000.png"),
               ("okww-now", r"probe\okww-now.png")]:
    im = Image.open(p).convert("RGB")
    out = rf"logs\shots\sample-{tag}.png"
    im.resize((im.width//2, im.height//2), Image.LANCZOS).save(out)
    print(f"{tag} {im.size} -> {out}")
