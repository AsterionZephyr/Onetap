"""refresh_assets.py — 更新图像资产（按当前程序版本重采）

用户要求：**先更新资产**；后续版本过期另谈（一般不会轻易改变）。

策略：
  1. 对每个目标：启动 -> 等就绪 -> 导航到任务页
  2. **程序化定位**关键元素（不凭坐标手工裁剪 —— INV-34）
  3. 保存资产 + 记录**采集时的程序版本**（INV-35）
  4. 逐个验证唯一性与自匹配

产出：
  - templates/*.png（更新）
  - templates/assets.json（元数据：版本、尺寸、页面、唯一性）
"""

import ctypes
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

import capture as C
import cleanup as CL
from orchestrator import (find_layer2, grab, force_foreground, click, c2s, top_at, R)
from template_probe import match_template
from nte_main import all_hits

ctypes.windll.shcore.SetProcessDpiAwareness(2)
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")
TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")
META = TPL / "assets.json"


def detect_hamburger(frame, x0=0, x1=70, y0=0, y1=220):
    """找 ☰（三条等距水平亮线）—— 程序化定位，不靠坐标猜测。"""
    sub = frame[y0:y1, x0:x1]
    g = sub.astype(np.float32).mean(axis=2)
    bright = g > 120
    rowsum = bright.sum(axis=1)
    lines = [i for i, v in enumerate(rowsum) if v >= 8]
    if len(lines) < 3:
        return None
    groups, s, prev = [], lines[0], lines[0]
    for i in lines[1:]:
        if i - prev > 2:
            groups.append((s, prev)); s = i
        prev = i
    groups.append((s, prev))
    for i in range(len(groups) - 2):
        a, b, c = groups[i], groups[i + 1], groups[i + 2]
        ga, gb = b[0] - a[1], c[0] - b[1]
        if abs(ga - gb) <= 2 and 2 <= ga <= 10:
            band = bright[a[0]:c[1] + 1]
            cols = np.where(band.any(axis=0))[0]
            if len(cols) < 6:
                continue
            return (x0 + int(cols.min()), y0 + a[0],
                    x0 + int(cols.max()), y0 + c[1])
    return None


def wait_ready(hwnd, ident_tpl, timeout=180):
    t0 = time.time()
    streak = 0
    while time.time() - t0 < timeout:
        force_foreground(hwnd)
        f, r, fw, fh = grab(hwnd)
        if f is None:
            time.sleep(2); continue
        s, _, _ = match_template(f, ident_tpl)
        streak = streak + 1 if s >= 0.90 else 0
        if streak >= 3:
            return True, f
        time.sleep(2)
    return False, None


def save_asset(name, img, meta, page, notes):
    p = TPL / name
    Image.fromarray(img).save(p)
    meta.append({
        "file": name,
        "w": int(img.shape[1]), "h": int(img.shape[0]),
        "page": page,
        "notes": notes,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
    })
    print(f"    保存 {name}  {img.shape[1]}x{img.shape[0]}")


def find_nte_second_layer(timeout=150):
    """严格找 ok-nte 的第二层窗口。

    ⚠️ 实测踩坑：`find_layer2('ok-nte')` 会匹配到**任何标题含 'ok-nte' 的窗口**，
    例如浏览器/编辑器里打开了 `OK-NTE-ADAPTATION.md` 的窗口。
    故这里要求标题形如 `ok-nte vX.Y.Z ... - ok-nte`（含版本号 + 分隔符）。
    """
    import re
    pat = re.compile(r"^ok-nte\s+v\d+\.\d+", re.I)
    t0 = time.time()
    while time.time() - t0 < timeout:
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        def cb(h, l):
            n = C.user32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 2)
                C.user32.GetWindowTextW(h, b, n + 2)
                t = b.value
                if pat.match(t):
                    cls = ctypes.create_unicode_buffer(256)
                    C.user32.GetClassNameW(h, cls, 256)
                    if "tauri" in cls.value.lower():
                        return True
                    r = R(); C.user32.GetWindowRect(h, ctypes.byref(r))
                    w, hh = r.r - r.l, r.b - r.t
                    if w > 500 and hh > 400 and C.user32.IsWindowVisible(h):
                        found.append((h, t, w, hh))
            return True

        C.user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(2)
    return None


def capture_nte(meta):
    exe = r"E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe"
    print("\n" + "=" * 70)
    print("采集 ok-nte 资产")
    print("=" * 70)
    CL.cleanup("ok-nte")
    subprocess.Popen([exe], cwd=r"E:\TOOLS\ScriptsGames\ok-nte")
    got = find_nte_second_layer()
    if not got:
        print("  [NG] 第二层未出现")
        return None
    hwnd, ver, _w, _h = got
    print(f"  第二层: hwnd={hwnd}  [{ver}]")

    # 身份锚点 = ☰（程序化定位）
    force_foreground(hwnd)
    f, r, fw, fh = grab(hwnd)
    box = detect_hamburger(f)
    if not box:
        print("  [NG] 未找到 ☰")
        return None
    bx0, by0, bx1, by1 = box
    pad = 3
    ident = f[max(0, by0 - pad):by1 + pad + 1, max(0, bx0 - pad):bx1 + pad + 1]
    print(f"  ☰ 定位 x={bx0}..{bx1} y={by0}..{by1}")

    ok, f = wait_ready(hwnd, ident)
    print(f"  就绪: {ok}")
    if not ok:
        return None

    save_asset("4_nte_menu.png", ident, meta, "任意（窗口固定元素）",
               "☰ 菜单图标，程序化定位，页面无关")

    # 导航到任务页（点侧栏 y=329）
    d = np.array(Image.open(TPL / "3_nte_daily.png").convert("RGB"))
    s, _, _ = match_template(f, d)
    if s < 0.90:
        nx, ny = c2s(hwnd, 30, 329)
        click(nx, ny)
        time.sleep(2.5)
        force_foreground(hwnd)
        f, r, fw, fh = grab(hwnd)

    s1, x1, y1 = match_template(f, d)
    print(f"  任务页 页面锚点(旧) score={s1:.4f}")
    if s1 < 0.90:
        print("  [NG] 未能到达任务页")
        return None

    # 重采页面锚点（「日历/图标 + 日常任务」文字区）
    #   由旧锚点位置反推：以匹配到的 y 行为准，取该行左侧文字区
    #   更稳的做法：在匹配点附近扫描文字行
    th, tw, _ = d.shape
    y0, x0 = y1, x1
    # 扩展为「图标 + 文字」，宽度取旧版比例（x 从锚点起 65px 宽）
    w_new = 70
    h_new = th
    xa, ya = max(0, x0 - 2), max(0, y0)
    xb, yb = min(fw, xa + w_new), min(fh, ya + h_new)
    page = f[ya:yb, xa:xb]
    save_asset("3_nte_daily.png", page, meta, "日常任务页",
               "「日历图标 + 日常任务」文字，页面锚点")
    Image.fromarray(f).save(OUT / "asset-nte-taskpage.png")

    # 动作锚点 = 「▶ 开始」按钮：在页面右下区域找青色按钮
    fr = f.astype(np.float32)
    R_, G_, B_ = fr[:, :, 0], fr[:, :, 1], fr[:, :, 2]
    cyan = (B_ > 150) & (G_ > 150) & (R_ < 130)
    # 限定在页面下半部
    cyan[:fh // 2] = False
    cols = np.where(cyan.sum(axis=0) > 5)[0]
    rows = np.where(cyan.sum(axis=1) > 5)[0]
    if len(cols) and len(rows):
        # 取最右侧那一块
        cx1_, cx0_ = cols.max(), cols.min()
        # 分离连续块
        groups, s_, prev = [], cols[0], cols[0]
        for c in cols[1:]:
            if c - prev > 10:
                groups.append((s_, prev)); s_ = c
            prev = c
        groups.append((s_, prev))
        gx0, gx1 = groups[-1]
        sub = cyan[:, gx0:gx1 + 1]
        rws = np.where(sub.sum(axis=1) > 3)[0]
        gy0, gy1 = rws.min(), rws.max()
        pad2 = 3
        act = f[max(0, gy0 - pad2):gy1 + pad2 + 1, max(0, gx0 - pad2):gx1 + pad2 + 1]
        save_asset("2_nte.png", act, meta, "日常任务页",
                   "「▶ 开始」按钮（青色，程序化定位）")
        print(f"  按钮定位 x={gx0}..{gx1} y={gy0}..{gy1}")

    # 侧栏任务图标（1_nte）—— 取图标列上 y=229 附近
    side = f[218:242, 14:46]
    save_asset("1_nte.png", side, meta, "任意（侧栏）", "侧栏任务图标")
    return ver


def verify_all(meta):
    print("\n" + "=" * 70)
    print("验证资产（唯一性 + 自匹配）")
    print("=" * 70)
    got = find_nte_second_layer(30)
    if not got:
        print("  无窗口可验证")
        return
    hwnd = got[0]
    force_foreground(hwnd)
    f, r, fw, fh = grab(hwnd)
    for m in meta:
        a = np.array(Image.open(TPL / m["file"]).convert("RGB"))
        if a.shape[0] > fh or a.shape[1] > fw:
            print(f"  {m['file']:<20} 大于窗口，跳过")
            continue
        s, x, y = match_template(f, a)
        hits = all_hits(f, a, 0.90, min_dist=max(20, a.shape[1] // 2))
        flag = "OK" if s > 0.90 else ("需导航" if s > 0.3 else "不匹配")
        print(f"  {m['file']:<20} 自匹配={s:.4f} @({x},{y})  候选={len(hits)}  {flag}")


def main():
    meta = []
    ver = capture_nte(meta)
    if ver:
        for m in meta:
            m["app_version"] = ver
    META.write_text(json.dumps({
        "note": "资产元数据。app_version = 采集时的程序版本（见 INV-35）",
        "captured": datetime.now().isoformat(timespec="seconds"),
        "assets": meta,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n元数据已写入 {META}")
    verify_all(meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
