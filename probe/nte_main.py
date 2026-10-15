"""nte_main.py — ok-nte 主界面适配勘察 + 模板定位

现在第二层（pythonw / Qt6112QWindowIcon）已就位。
本脚本：
  1. 定位第二层窗口并勘察
  2. 抓整窗落盘
  3. 用 1_nte.png / 2_nte.png 匹配，并做**唯一性检查**（INV-24）
  4. 若找到「开始」按钮，计算点击坐标
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

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")


class R(ctypes.Structure):
    _fields_ = [("l", wt.LONG), ("t", wt.LONG), ("r", wt.LONG), ("b", wt.LONG)]


def find_nte_layer2():
    """找第二层：class 含 Qt，标题含 ok-nte"""
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n == 0:
            return True
        b = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(h, b, n + 2)
        t = b.value
        if "ok-nte" not in t.lower():
            return True
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        r = R()
        user32.GetWindowRect(h, ctypes.byref(r))
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        res.append((h, c.value, t, pid.value, r.r - r.l, r.b - r.t,
                    bool(user32.IsWindowVisible(h))))
        return True

    user32.EnumWindows(cb, 0)
    return res


def all_hits(frame, tpl, thresh, min_dist):
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
    print("=" * 72)
    print("ok-nte 主界面适配勘察")
    print("=" * 72)

    ws = find_nte_layer2()
    print(f"\n[发现] 标题含 ok-nte 的窗口 {len(ws)} 个：")
    for h, c, t, pid, w, hh, v in ws:
        print(f"  hwnd={h} pid={pid} {w}x{hh} vis={v} class={c}")
        print(f"      title=[{t}]")

    # 取最大的那个作为主界面
    ws = [x for x in ws if x[4] > 200 and x[5] > 200 and x[6]]
    if not ws:
        print("[NG] 无可见的主界面窗口")
        return 1
    ws.sort(key=lambda x: -x[4] * x[5])
    hwnd, cls, title, pid, w, h, v = ws[0]

    user32.ShowWindow(hwnd, 9)
    time.sleep(0.4)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.r - r.l, r.b - r.t
    fg_ok = user32.GetForegroundWindow() == hwnd
    print(f"\n[主界面] hwnd={hwnd} pid={pid}")
    print(f"  class={cls}  title=[{title}]")
    print(f"  rect=({r.l},{r.t})-({r.r},{r.b})  {w}x{h}  前台={fg_ok}")

    cnt = [0]

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def ccb(ch, l):
        cnt[0] += 1
        return True

    user32.EnumChildWindows(hwnd, ccb, 0)
    print(f"  子窗口数={cnt[0]}")

    got = C.capture_region(r.l, r.t, w, h)
    d, fw, fh = got
    frame = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    Image.fromarray(frame).save(OUT / "nte-main.png")
    st = C.frame_stats(d, fw, fh)
    print(f"  抓帧 {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")
    print(f"  落盘 nte-main.png")

    print(f"\n{'='*72}")
    print("模板匹配 + 唯一性检查")
    print(f"{'='*72}")
    for name in ["1_nte.png", "2_nte.png"]:
        tp = np.array(Image.open(TPL / name).convert("RGB"))
        th, tw, _ = tp.shape
        print(f"\n[{name}] {tw}x{th}")
        sc, mx, my = match_template(frame, tp)
        print(f"  最佳 score={sc:.4f} pos=({mx},{my}) 中心=({mx+tw//2},{my+th//2})")
        hits = all_hits(frame, tp, 0.85, min_dist=max(20, tw // 2))
        print(f"  >=0.85 的候选数 = {len(hits)}")
        for i, (y, x, s) in enumerate(hits[:6]):
            print(f"     [{i}] score={s:.4f} pos=({x},{y})")
        if hits:
            y, x, s = hits[0]
            c = frame[max(0, y - 10):y + th + 10, max(0, x - 10):x + tw + 10]
            Image.fromarray(c).save(OUT / f"nte-match-{name.replace('.png','')}.png")
            print(f"     落盘 nte-match-{name.replace('.png','')}.png")

    # 同时列出所有绿色块（可能的「开始」按钮）
    print(f"\n{'='*72}")
    print("绿色按钮候选（「开始」通常是彩色按钮）")
    print(f"{'='*72}")
    f = frame.astype(np.float32)
    Rr, Gg, Bb = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    for label, mask in [
        ("绿色", (Gg > 130) & (Gg - Rr > 35) & (Gg - Bb > 25)),
        ("青蓝色", (Bb > 150) & (Gg > 150) & (Rr < 120)),
    ]:
        cols = np.where(mask.sum(axis=0) > 6)[0]
        rows = np.where(mask.sum(axis=1) > 6)[0]
        if len(cols) and len(rows):
            print(f"  [{label}] x={cols.min()}..{cols.max()} y={rows.min()}..{rows.max()}"
                  f"  像素数={int(mask.sum())}")
        else:
            print(f"  [{label}] 无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
