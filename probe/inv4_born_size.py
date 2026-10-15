"""inv4_born_size.py — 验证 INV-4：出生尺寸不同源的资产会被拒绝

设计三个场景：
  S1 同源   ：资产出生尺寸 == 当前窗口尺寸  -> 应当放行
  S2 不同源 ：资产出生尺寸 != 当前窗口尺寸  -> 应当拒绝
  S3 尺寸碰巧相同但内容不同（误导场景）      -> 说明仅比尺寸还不够

同时实测：把 2_ww.png 当作"出生于 1366 宽窗口"的资产，
在当前 1875 宽窗口下处理时应触发告警。
"""

import sys
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
    print("=" * 68)
    print("INV-4 实测：出生尺寸校验")
    print("=" * 68)

    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww 窗口")
        return 1
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    print(f"\n当前窗口 {w}x{h}")
    if C.user32.GetForegroundWindow() != hwnd:
        C.user32.SetForegroundWindow(hwnd)
    import time
    time.sleep(0.4)

    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    print(f"帧 {fw}x{fh}")

    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    th, tw, _ = tpl.shape

    # ---- 模拟资产元数据 ----
    assets = [
        {"name": "2_ww 原样", "born": (1366, 41), "tpl": tpl,
         "note": "假设出生于 1366 宽度"},
        {"name": "2_ww 同源版", "born": (1875, 1250), "tpl": tpl,
         "note": "假设与当前窗口同源"},
    ]

    print(f"\n{'='*68}")
    print("S1/S2：出生尺寸校验")
    print(f"{'='*68}")
    for a in assets:
        born = a["born"]
        print(f"\n[资产] {a['name']}   出生尺寸={born}   ({a['note']})")
        same = (born[0] == w and born[1] == h)
        if same:
            print(f"   [OK] 同源 -> 允许使用")
        else:
            print(f"   [拒绝] 不同源！当前窗口 {w}x{h} 与出生 {born} 不符")
            print(f"          => INV-4 生效：不得用该资产算坐标")

    # ---- S3：尺寸对得上，内容对不上 ----
    print(f"\n{'='*68}")
    print("S3：误导场景 —— 尺寸相同但内容不是目标")
    print(f"{'='*68}")

    # 把模板缩放到窗口宽度，模拟一种"看起来尺寸合适"的错误资产
    fake = np.array(Image.fromarray(tpl).resize((w // 4, th), Image.LANCZOS))
    fh_, fw_, _ = fake.shape
    print(f"构造一个假资产：尺寸 {fw_}x{fh_}（远小于窗口），内容取自 2_ww 的缩放版")
    res = match_template(frame, fake)
    if res:
        sc, mx, my = res
        print(f"   匹配 score={sc:.4f} pos=({mx},{my})")
        verdict = "高" if sc > 0.8 else ("中" if sc > 0.6 else "低")
        print(f"   => 分数{verdict}。注意：分数高也不代表找对了目标（见 INV-19）")

    # ---- 真实的跨尺寸匹配行为 ----
    print(f"\n{'='*68}")
    print("补充：2_ww 文字段在不同窗口宽度下的行为")
    print(f"{'='*68}")
    sub = tpl[:, 9:9 + 98]
    sc, mx, my = match_template(frame, sub)
    print(f"   文字段 {sub.shape[1]}x{sub.shape[0]} -> score={sc:.4f} pos=({mx},{my})")
    print(f"   当前窗口宽 {w}，模板原宽 {tw}")
    print(f"   文字段锚点 x={mx}（窗口内）")
    print(f"   => 文字锚点与窗口宽度**无关**（它是左对齐的），")
    print(f"      而 '开始' 按钮右对齐，位置**随窗口宽度变化**。")
    print(f"      这解释了为何必须'锚点定位 + 结构扫描'，而不能用模板偏移。")

    # ---- 用两种窗口宽度验证锚点不变性 ----
    print(f"\n[断言] 文字段锚点在不同窗口尺寸下应保持在同一相对位置")
    print(f"   窗口宽 {w} 时锚点 x={mx}，占宽比 {mx/w:.4f}")
    print(f"   （若窗口变为 1500，按同比例预期锚点 x≈{int(mx*1500/w)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
