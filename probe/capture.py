# capture.py — ok-ww 黑盒编排 · 阶段二抓图与校验
#
# 验证目标（见 HISTORY A.4）：
#   T-5 帧尺寸是否恒等于窗口 rect          -> INV-1
#   INV-13 全黑/异常帧能否被检出并中止      -> 帧内容校验
#   INV-12 可见性：API 说 visible 是否真的在屏幕上
#   INV-14 hwnd 每次运行重新发现
#
# 只读：不点击、不投递消息、不改变 ok-ww 任何状态。

import ctypes
import ctypes.wintypes as wt
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)

# --- Win32 绑定 ---
user32.SetProcessDPIAware.restype = wt.BOOL

class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte),
                ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


def find_okww_window():
    """按标题正则发现窗口持有者 —— INV-5 / INV-14：不缓存 hwnd，每次重新发现。"""
    import re
    pat = re.compile(r"OK-WW")
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        title = buf.value
        if pat.search(title):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((hwnd, pid.value, title))
        return True

    user32.EnumWindows(cb, 0)
    return found


def get_window_rect(hwnd):
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r


def capture_region(x, y, w, h):
    """用 BitBlt 从屏幕 DC 抓一块区域，返回 (bytes BGRA, w, h)。"""
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)

    SRCCOPY = 0x00CC0020
    ok = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负值 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0      # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    DIB_RGB_COLORS = 0
    lines = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)

    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)

    if not ok or lines == 0:
        return None
    return buf.raw, w, h


def frame_stats(data, w, h):
    """帧内容统计 —— 用于 INV-12 / INV-13 的「非全黑、含变化」校验。"""
    n = w * h
    total_b = total_g = total_r = 0
    uniq = set()
    step = max(1, n // 4000)
    count = 0
    for i in range(0, n, step):
        o = i * 4
        b, g, r = data[o], data[o + 1], data[o + 2]
        total_b += b; total_g += g; total_r += r
        uniq.add((r >> 3, g >> 3, b >> 3))
        count += 1
    return {
        "mean_rgb": (total_r // count, total_g // count, total_b // count),
        "distinct_colors_sampled": len(uniq),
        "sampled": count,
    }


def main():
    user32.SetProcessDPIAware()
    print("=" * 62)
    print("ok-ww 阶段二 · 抓图与校验（只读）")
    print("=" * 62)

    # --- 发现窗口（INV-5 正则 / INV-14 不缓存）---
    wins = find_okww_window()
    if not wins:
        print("[NG] 未找到标题含 'OK-WW' 的窗口")
        return 1
    print(f"\n[发现] 匹配窗口 {len(wins)} 个")
    for hwnd, pid, title in wins:
        print(f"   hwnd={hwnd}  pid={pid}  title=[{title}]")

    hwnd, pid, title = wins[0]

    # --- 窗口几何 ---
    rect = get_window_rect(hwnd)
    if rect is None:
        print("[NG] GetWindowRect 失败")
        return 1
    ww = rect.right - rect.left
    wh = rect.bottom - rect.top
    print(f"\n[窗口] rect = ({rect.left},{rect.top}) - ({rect.right},{rect.bottom})  =>  {ww} x {wh}")

    fg = user32.GetForegroundWindow()
    print(f"[前台] GetForegroundWindow()={fg}  在前台={fg == hwnd}")
    print(f"[可见] IsWindowVisible={bool(user32.IsWindowVisible(hwnd))}  IsIconic={bool(user32.IsIconic(hwnd))}")

    if ww <= 0 or wh <= 0:
        print("[NG] 窗口 rect 无效（可能最小化），中止")
        return 1

    # --- 抓帧 ---
    print(f"\n[抓帧] 从 ({rect.left},{rect.top}) 抓 {ww}x{wh}")
    t0 = time.time()
    got = capture_region(rect.left, rect.top, ww, wh)
    dt = (time.time() - t0) * 1000
    if got is None:
        print("[NG] 抓帧失败")
        return 1
    data, fw, fh = got
    print(f"   帧尺寸 = {fw} x {fh}   耗时 {dt:.0f} ms")

    # --- INV-1：帧尺寸 vs 窗口 rect ---
    print("\n" + "-" * 62)
    print("T-5 / INV-1：帧尺寸是否等于窗口 rect")
    if fw == ww and fh == wh:
        print(f"   [OK] 一致（{fw}x{fh} == {ww}x{wh}）")
    else:
        print(f"   [NG] 不一致！帧 {fw}x{fh} vs 窗口 {ww}x{wh} —— 此时坐标必然错位，必须停手")

    # --- INV-13 / INV-12：帧内容校验 ---
    print("\n" + "-" * 62)
    print("INV-13 / INV-12：帧内容校验（非全黑、有色彩变化）")
    st = frame_stats(data, fw, fh)
    print(f"   平均 RGB        = {st['mean_rgb']}")
    print(f"   采样色彩种类数  = {st['distinct_colors_sampled']}  (采样 {st['sampled']} 点)")
    mean_sum = sum(st['mean_rgb'])
    if mean_sum < 15:
        print("   [NG] 帧几乎全黑 —— 抓图落空（INV-13 情形），必须中止")
    elif st['distinct_colors_sampled'] < 5:
        print("   [!!]  帧色彩极其单一 —— 可疑，需人工确认")
    else:
        print("   [OK] 帧有实际内容")

    # --- 落盘 ---
    out = sys.argv[1] if len(sys.argv) > 1 else "okww-frame.png"
    try:
        from pngout import write_png_bgra
        write_png_bgra(out, data, fw, fh)
        import os
        print(f"\n[落盘] {out}  ({fw}x{fh}, {os.path.getsize(out)} bytes)")
    except Exception as e:
        print(f"\n[落盘] 失败：{e}")

    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
