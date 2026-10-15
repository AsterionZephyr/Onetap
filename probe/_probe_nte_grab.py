# -*- coding: utf-8 -*-
"""抓一帧干净（已置前台）的 ok-nte 帧落盘。

用法：
    python -X utf8 probe/_probe_nte_grab.py 输出路径
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from orchestrator import capture, input as input_mod, match, programs, window

OUT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "logs/shots/nte-clean.png")


def main():
    w = window.find_window(program=programs.NTE)
    if not w:
        print("[NG] ok-nte 未运行")
        return 1
    hwnd = w["hwnd"]
    try:
        input_mod.ensure_foreground(hwnd, tries=6, interval=0.5, log=print)
    except Exception as e:
        print(f"[警告] 置前台失败：{e}")

    f = capture.grab_frame(hwnd)
    print(f"帧 {f.width}x{f.height} 均值{f.stats['mean_rgb']} "
          f"色彩{f.stats['distinct_colors_sampled']}")
    ident = match.verify_identity(f.rgb)
    print(f"身份 = {ident}")
    Image.fromarray(f.rgb).save(OUT)
    print(f"落盘 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
