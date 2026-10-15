"""run_daily2.py — 端到端 v2：修正锚点歧义（INV-24）+ 唯一性检查

与 v1 的关键区别：
  v1 锚点 = tpl[:, 9:9+98]  （日历起头）  -> 歧义！与进度面板日志行的图标撞车
  v2 锚点 = tpl[:, 35:72]   （「每日任务」四字）-> 实测全帧唯一

新增校验（依次全过才点击）：
  1. 窗口发现 + rect                        (INV-14)
  2. SetForegroundWindow + 验证             (INV-22)
  3. 帧尺寸 == 窗口 rect                     (INV-1)
  4. 帧内容非全黑                            (INV-13)
  5. 身份校验：侧栏 1_ww 在 (16,215) 附近     (INV-12/INV-18)
  6. 锚点匹配 score >= 0.90                  (§3.4)
  7. **锚点唯一性**：全帧 >=0.85 的位置只有一个 (INV-24)
  8. 同行扫描「开始」按钮 + 交叉验证（y 落在行内）
  9. 遮挡判定：目标坐标处最顶层 == ok-ww       (INV-23)

用法：python run_daily2.py [--dry-run]
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
user32 = C.user32

PUL = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


# 锚点定义：'每日任务' 四字
ANCHOR_X0, ANCHOR_X1 = 35, 72
SIDEBAR = "1_ww.png"


def click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y)
    time.sleep(0.08)
    nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    for f in (0x0001 | 0x8000, 0x0002, 0x0004):
        i = INPUT(); i.type = 0
        i.mi.dx, i.mi.dy, i.mi.dwFlags = nx, ny, f
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
        time.sleep(0.04)


def c2s(hwnd, cx, cy):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P(cx, cy); user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def top_at(x, y):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    return user32.GetAncestor(user32.WindowFromPoint(P(x, y)), 2)


def all_hits(frame, tpl, thresh, min_dist):
    """全帧扫描，返回所有 >= thresh 的局部极大（用于唯一性检查）。"""
    fh, fw, _ = frame.shape
    th, tw, _ = tpl.shape
    if th > fh or tw > fw:
        return []
    f = frame.astype(np.float32).mean(axis=2)
    t = tpl.astype(np.float32).mean(axis=2)
    tc = t - t.mean(); tn = np.sqrt((tc ** 2).sum())
    if tn == 0:
        return []
    sm = np.full((fh - th + 1, fw - tw + 1), -2.0, dtype=np.float32)
    for y in range(fh - th + 1):
        row = f[y:y + th]
        for x in range(fw - tw + 1):
            win = row[:, x:x + tw]
            wc = win - win.mean(); wn = np.sqrt((wc ** 2).sum())
            if wn:
                sm[y, x] = float((wc * tc).sum() / (wn * tn))
    order = np.dstack(np.unravel_index(np.argsort(-sm, axis=None), sm.shape))[0]
    hits = []
    for yx in order:
        y, x = int(yx[0]), int(yx[1])
        if sm[y, x] < thresh:
            break
        if all(abs(y - h[0]) > min_dist or abs(x - h[1]) > min_dist for h in hits):
            hits.append((y, x, float(sm[y, x])))
    return hits


def main():
    dry = "--dry-run" in sys.argv
    print("=" * 70)
    print("端到端 v2（修正锚点歧义）" + ("   [DRY RUN]" if dry else ""))
    print("=" * 70)

    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww 窗口")
        return 1
    hwnd, pid, title = wins[0]

    # 2) 还原 + 置前台
    user32.ShowWindow(hwnd, 9)
    time.sleep(0.5)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    fg_ok = user32.GetForegroundWindow() == hwnd
    r = C.get_window_rect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    print(f"\n[1-2] hwnd={hwnd} pid={pid}  {w}x{h}  前台={fg_ok}")
    if w < 100:
        print("      [NG] 窗口尺寸异常（最小化？），中止")
        return 1
    if not fg_ok:
        print("      [NG] 置前台失败，中止")
        return 1

    # 3) 抓帧
    got = C.capture_region(r.left, r.top, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    print(f"\n[3] 帧 {fw}x{fh}   INV-1: {'OK' if (fw,fh)==(w,h) else 'NG'}")
    if (fw, fh) != (w, h):
        return 1

    # 4) 内容
    st = C.frame_stats(d, fw, fh)
    print(f"[4] 内容 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")
    if sum(st["mean_rgb"]) < 15:
        print("    [NG] 全黑，中止")
        return 1

    # 5) 身份校验
    side = np.array(Image.open(TPL / SIDEBAR).convert("RGB"))
    ssc, smx, smy = match_template(frame, side)
    ok_id = ssc > 0.95 and abs(smx - 16) < 12 and abs(smy - 215) < 12
    print(f"[5] 身份校验 侧栏 score={ssc:.4f} pos=({smx},{smy})  {'OK' if ok_id else 'NG'}")
    if not ok_id:
        print("    [NG] 帧不是 ok-ww 或侧栏位置异常，中止")
        return 1

    # 6-7) 锚点 + 唯一性
    tpl = np.array(Image.open(TPL / "2_ww.png").convert("RGB"))
    anchor = tpl[:, ANCHOR_X0:ANCHOR_X1]
    ah = anchor.shape[0]
    hits = all_hits(frame, anchor, 0.85, min_dist=30)
    print(f"\n[6] 锚点「每日任务」四字 {anchor.shape[1]}x{ah}")
    for i, (y, x, s) in enumerate(hits[:5]):
        print(f"      [{i}] score={s:.4f} pos=({x},{y})")
    if not hits:
        print("    [NG] 无匹配，中止")
        return 1
    top_score, top_x, top_y = hits[0][2], hits[0][1], hits[0][0]
    if top_score < 0.90:
        print(f"    [NG] 最高分 {top_score:.4f} < 0.90，中止")
        return 1
    print(f"[7] 唯一性检查：>=0.85 的位置数 = {len(hits)}")
    if len(hits) > 1:
        print(f"    [NG] 锚点不唯一（{len(hits)} 个候选），拒绝点击（INV-24）")
        for y, x, s in hits[1:5]:
            print(f"         次候选 score={s:.4f} pos=({x},{y})")
        return 1
    print("    [OK] 锚点唯一")

    row_y0, row_y1 = top_y, top_y + ah
    print(f"      行范围 y = {row_y0}..{row_y1}")

    # 8) 同行扫描按钮
    by0, by1 = max(0, row_y0 - 5), min(fh, row_y1 + 5)
    band = frame[by0:by1]
    g = band.astype(np.float32).mean(axis=2)
    bright = g > 200
    colsum = bright.sum(axis=0)
    cols = np.where(colsum > (by1 - by0) * 0.35)[0]
    if not len(cols):
        print("\n[8] [NG] 该行未找到白色按钮块，中止")
        return 1
    groups = []
    s = prev = cols[0]
    for c in cols[1:]:
        if c - prev > 8:
            groups.append((s, prev)); s = c
        prev = c
    groups.append((s, prev))
    bx0, bx1 = groups[-1]
    bcx = (bx0 + bx1) // 2
    sub_b = bright[:, bx0:bx1 + 1]
    rows = np.where(sub_b.sum(axis=1) > 3)[0]
    bcy = by0 + (rows.min() + rows.max()) // 2
    print(f"\n[8] 按钮 x={bx0}..{bx1} y={by0+rows.min()}..{by0+rows.max()}  中心=({bcx},{bcy})")
    if not (row_y0 <= bcy <= row_y1):
        print(f"    [NG] 交叉验证失败：按钮 y={bcy} 不在行 {row_y0}..{row_y1}")
        return 1
    print("    [OK] 交叉验证通过")

    # 9) 遮挡判定
    sx, sy = c2s(hwnd, bcx, bcy)
    topw = top_at(sx, sy)
    print(f"\n[9] 屏幕坐标=({sx},{sy})  该处顶层 hwnd={topw}  是ok-ww={topw == hwnd}")
    if topw != hwnd:
        print("    [NG] 被遮挡，中止（INV-23）")
        return 1
    print("    [OK] 未被遮挡")

    crop = frame[max(0, bcy - 30):bcy + 30, max(0, bcx - 100):bcx + 80]
    Image.fromarray(crop).save(OUT / "v2-about-to-click.png")
    print("    落盘 v2-about-to-click.png")

    if dry:
        print("\n[DRY RUN] 未点击")
        return 0

    print(f"\n[10] 点击 ({sx},{sy}) ...")
    click(sx, sy)
    time.sleep(1.0)
    r2 = C.get_window_rect(hwnd)
    print(f"     点击后 {r2.right-r2.left}x{r2.bottom-r2.top}  前台={user32.GetForegroundWindow()==hwnd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
