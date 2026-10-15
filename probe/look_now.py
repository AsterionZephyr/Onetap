"""look_now.py — 抓当前 ok-ww 整窗并落盘，供肉眼确认当前处于哪个页面（只读）"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

from template_probe import capture_okww, OUT_DIR


def main():
    hwnd, pid, title, r, fw, fh, frame = capture_okww()
    print(f"窗口 {fw}x{fh} @ ({r.left},{r.top})  hwnd={hwnd} pid={pid}")
    out = OUT_DIR / "okww-now.png"
    Image.fromarray(frame).save(out)
    print(f"落盘 {out}  ({out.stat().st_size} bytes)")
    # 顺带给出下半部/右半部的亮度分布，帮助判断页面结构
    g = frame.astype(np.float32).mean(axis=2)
    print(f"整体亮度 均值={g.mean():.1f} min={g.min():.0f} max={g.max():.0f}")
    for name, sl in [("上半", g[:fh // 2]), ("下半", g[fh // 2:]),
                     ("左1/4", g[:, :fw // 4]), ("右1/4", g[:, 3 * fw // 4:])]:
        print(f"  {name}: 均值={sl.mean():.1f} 最大={sl.max():.0f}")


if __name__ == "__main__":
    main()
