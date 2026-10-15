"""anchor_threshold.py — 研究匹配分数的分布，为阈值给出实证依据

问题：同一模板在同尺寸窗口下，
  - 侧栏收起时：score = 1.0000
  - 侧栏展开时：score = 0.9402
  - 页面不对时：score = 0.4722

需要区分"亚像素偏移导致的轻微下降"与"根本没找到"。
本脚本对比若干候选特征的表现，并给出阈值建议。
"""

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")


def main():
    wins = C.find_okww_window()
    hwnd, pid, title = wins[0]
    C.user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    print(f"窗口 {w}x{h}")

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape

    # 候选特征：不同宽度的文字片段
    cands = [
        ("日历图标",            9, 17),
        ("日历+每日",           9, 45),
        ("每日任务四字",        35, 72),
        ("当前用(9..106)",      9, 98),
        ("文字全段(9..452)",    9, 444),
        ("整行(0..1366)",       0, 1366),
    ]
    print(f"\n{'特征':>18} {'宽':>5} {'score':>8} {'pos':>14}  判定")
    for name, x0, x1 in cands:
        x1 = min(x1, tw)
        sub = tpl[:, x0:x1]
        if sub.shape[1] < 6:
            continue
        sc, mx, my = match_template(frame, sub)
        if sc > 0.95:
            v = "优秀"
        elif sc > 0.90:
            v = "良好"
        elif sc > 0.80:
            v = "可用"
        elif sc > 0.60:
            v = "可疑"
        else:
            v = "失败"
        print(f"{name:>18} {sub.shape[1]:>5} {sc:>8.4f} {str((mx,my)):>14}  {v}")

    print(f"\n{'='*68}")
    print("参考区间（本环境实测）")
    print(f"{'='*68}")
    print("  正确页面 + 侧栏收起 : 1.0000   （像素级完全一致）")
    print("  正确页面 + 侧栏展开 : 0.9402   （亚像素/布局偏移）")
    print("  错误页面            : 0.4722   （根本不存在）")
    print()
    print("  => 0.4722 与 0.9402 之间有 **巨大间隔**，阈值取 0.85~0.90 是安全的。")
    print("  => 但 **不能用 0.95**：正确页面在侧栏展开时会降到 0.9402，会被误拒。")
    print()
    print("  建议：accept >= 0.90，reject < 0.85，中间区间告警并要求交叉验证。")

    # 打印当前页面里『每日任务』行的实际位置供复核
    sub = tpl[:, 9:9 + 98]
    sc, mx, my = match_template(frame, sub)
    print(f"\n[当前] 文字段 score={sc:.4f} pos=({mx},{my})")
    if sc > 0.90:
        crop = frame[max(0,my-10):my+th+10, max(0,mx-20):mx+sub.shape[1]+20]
        Image.fromarray(crop).save(OUT / "anchor-check.png")
        print(f"  落盘 anchor-check.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
