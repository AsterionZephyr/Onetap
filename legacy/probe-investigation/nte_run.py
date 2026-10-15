"""nte_run.py — ok-nte 端到端：定位「日常任务」页 -> 点击「开始」

锚点策略（修正 2_nte.png 不唯一的问题）：
  - 主锚点 = 3_nte_daily.png（「日常任务」文字）—— 提供**页面上下文**
  - 次锚点 = 2_nte.png（「▶ 开始」按钮）—— 在**该页**内定位按钮
  - 二者缺一不可：只有按钮会匹配到别的页；只有文字则不知按钮在哪

九道校验（与 ok-ww 一致）：
  1 窗口发现  2 置前台验证  3 帧尺寸  4 内容非全黑
  5 主锚点唯一  6 副锚点唯一  7 交叉验证（按钮在页面下半部）
  8 遮挡判定  9 点击

用法：python nte_run.py [--dry-run]
"""

import sys
import time
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template
from nte_main import find_nte_layer2, all_hits, R

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")

PUL = ctypes.POINTER(ctypes.c_ulong)


class MI(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("md", ctypes.c_ulong), ("fl", ctypes.c_ulong),
                ("t", ctypes.c_ulong), ("ex", PUL)]


class IN(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MI)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


def click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y); time.sleep(0.1)
    nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    for fl in (0x0001 | 0x8000, 0x0002, 0x0004):
        i = IN(); i.type = 0
        i.mi.dx, i.mi.dy, i.mi.fl = nx, ny, fl
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(IN))
        time.sleep(0.05)


def c2s(h, cx, cy):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P(cx, cy); user32.ClientToScreen(h, ctypes.byref(p))
    return p.x, p.y


def top_at(x, y):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    return user32.GetAncestor(user32.WindowFromPoint(P(x, y)), 2)


def main():
    dry = "--dry-run" in sys.argv
    print("=" * 72)
    print("ok-nte 端到端：日常任务 -> 开始" + ("   [DRY RUN]" if dry else ""))
    print("=" * 72)

    ws = [x for x in find_nte_layer2() if x[4] > 200 and x[6]]
    if not ws:
        print("[NG] 未找到 ok-nte 主窗口")
        return 1
    ws.sort(key=lambda x: -x[4] * x[5])
    hwnd, cls, title, pid = ws[0][0], ws[0][1], ws[0][2], ws[0][3]

    user32.ShowWindow(hwnd, 9)
    time.sleep(0.4)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.r - r.l, r.b - r.t
    fg_ok = user32.GetForegroundWindow() == hwnd
    print(f"\n[1-2] hwnd={hwnd} pid={pid} {w}x{h} @({r.l},{r.t})")
    print(f"      class={cls}")
    print(f"      title=[{title}]")
    print(f"      前台={fg_ok}")
    if w < 100 or not fg_ok:
        print("      [NG] 窗口异常或置前台失败")
        return 1

    got = C.capture_region(r.l, r.t, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    print(f"\n[3] 帧 {fw}x{fh}  INV-1 {'OK' if (fw,fh)==(w,h) else 'NG'}")
    if (fw, fh) != (w, h):
        return 1

    st = C.frame_stats(d, fw, fh)
    print(f"[4] 内容 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")
    if sum(st["mean_rgb"]) < 15:
        print("    [NG] 全黑")
        return 1

    # 5) 主锚点：日常任务
    a1 = np.array(Image.open(TPL / "3_nte_daily.png").convert("RGB"))
    h1 = all_hits(frame, a1, 0.90, min_dist=20)
    print(f"\n[5] 主锚点「日常任务」{a1.shape[1]}x{a1.shape[0]}")
    for i, (y, x, s) in enumerate(h1[:5]):
        print(f"      [{i}] {s:.4f} @({x},{y})")
    if not h1:
        print("    [NG] 未找到「日常任务」——不在该页，中止")
        return 1
    if len(h1) > 1:
        print(f"    [NG] 主锚点不唯一（{len(h1)} 个），中止")
        return 1
    if h1[0][2] < 0.90:
        print("    [NG] 分数不足")
        return 1
    print("    [OK] 唯一，确认在「日常任务」页")

    # 6) 副锚点：开始按钮
    a2 = np.array(Image.open(TPL / "2_nte.png").convert("RGB"))
    th2, tw2, _ = a2.shape
    h2 = all_hits(frame, a2, 0.90, min_dist=40)
    print(f"\n[6] 副锚点「▶ 开始」{tw2}x{th2}")
    for i, (y, x, s) in enumerate(h2[:5]):
        print(f"      [{i}] {s:.4f} @({x},{y})")
    if not h2:
        print("    [NG] 未找到「开始」按钮")
        return 1
    if len(h2) > 1:
        print(f"    [NG] 按钮不唯一（{len(h2)} 个），中止")
        return 1
    by, bx, bs = h2[0]
    if bs < 0.90:
        print(f"    [NG] 按钮分数 {bs:.4f} 不足")
        return 1
    print("    [OK] 唯一")

    bcx, bcy = bx + tw2 // 2, by + th2 // 2

    # 7) 交叉验证：按钮应在页面下半部，且与文字同一页
    print(f"\n[7] 交叉验证")
    print(f"      文字锚点 y={h1[0][0]}  按钮中心 y={bcy}  窗口高 {fh}")
    if bcy < fh * 0.5:
        print("      [!!] 按钮不在页面下半部，可疑")
    else:
        print(f"      [OK] 按钮位于页面下半部（{bcy/fh:.0%} 处）")

    crop = frame[max(0, by - 12):by + th2 + 12, max(0, bx - 16):bx + tw2 + 16]
    Image.fromarray(crop).save(OUT / "nte-about-to-click.png")
    print(f"      落盘 nte-about-to-click.png")

    # 8) 遮挡判定
    sx, sy = c2s(hwnd, bcx, bcy)
    topw = top_at(sx, sy)
    print(f"\n[8] 屏幕坐标=({sx},{sy})  顶层 hwnd={topw}  是ok-nte={topw==hwnd}")
    if topw != hwnd:
        print("    [NG] 被遮挡，中止")
        return 1
    print("    [OK] 未被遮挡")

    if dry:
        print("\n[DRY RUN] 未点击")
        return 0

    print(f"\n[9] 点击 ({sx},{sy}) ...")
    click(sx, sy)
    time.sleep(1.5)

    r2 = R(); user32.GetWindowRect(hwnd, ctypes.byref(r2))
    print(f"     点击后 {r2.r-r2.l}x{r2.b-r2.t}  前台={user32.GetForegroundWindow()==hwnd}")
    got2 = C.capture_region(r2.l, r2.t, r2.r-r2.l, r2.b-r2.t)
    if got2:
        d2, w2, h2_ = got2
        f2 = np.frombuffer(d2, dtype=np.uint8).reshape(h2_, w2, 4)[:, :, [2, 1, 0]]
        Image.fromarray(f2).save(OUT / "nte-after-start.png")
        # 按钮是否还在？（点击后可能变为停止/暂停）
        if th2 <= h2_ and tw2 <= w2:
            s_after, _, _ = match_template(f2, a2)
            print(f"     点击后「开始」按钮 score={s_after:.4f}"
                  f"  {'(仍在)' if s_after > 0.9 else '(已变化/消失)'}")
        print(f"     落盘 nte-after-start.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
