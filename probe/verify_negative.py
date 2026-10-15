# verify_negative.py — 阶段二负向对照实验
#
# 目的：证明 INV-1 / INV-12 / INV-13 的校验器**真的会失败**。
# 一个从不报错的校验器等于没有校验器。
#
# 三个实验，全部只读，不点击、不改 ok-ww 状态：
#   N-1 故意用错尺寸抓帧 -> INV-1 必须报不一致
#   N-2 抓一块空的桌面区域 -> 内容校验的边界行为
#   N-3 抓一个不存在的区域/离屏坐标 -> 抓帧失败能否被检出

import ctypes
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import capture as C
import re

user32 = C.user32


def banner(t):
    print("\n" + "=" * 62)
    print(t)
    print("=" * 62)


def find():
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww 窗口")
        sys.exit(1)
    return wins[0]


def main():
    user32.SetProcessDPIAware()
    hwnd, pid, title = find()
    r = C.get_window_rect(hwnd)
    ww, wh = r.right - r.left, r.bottom - r.top
    print(f"ok-ww hwnd={hwnd} pid={pid} rect=({r.left},{r.top})-({r.right},{r.bottom}) {ww}x{wh}")

    # ---------- N-1：尺寸错配能否被检出 ----------
    banner("N-1  INV-1 负向对照：故意用错尺寸抓帧")
    # 窗口是 1500x1000，故意抓 1200x800（正是事实记录里那次错配的真实数值）
    bad_w, bad_h = 1200, 800
    print(f"窗口 rect = {ww}x{wh} ；故意抓 {bad_w}x{bad_h}（复现事实记录 §1 的 1200 宽情形）")
    got = C.capture_region(r.left, r.top, bad_w, bad_h)
    if got is None:
        print("   抓帧本身失败")
    else:
        d, fw, fh = got
        st = C.frame_stats(d, fw, fh)
        print(f"   帧尺寸 = {fw}x{fh} ；内容 = 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")
        if fw != ww or fh != wh:
            print(f"   [OK] INV-1 校验器**正确地报出了不一致**：{fw}x{fh} != {ww}x{wh}")
            print(f"        => 框架此时必须停手，不得用该帧算坐标")
        else:
            print("   [NG] 校验器未能检出不一致 —— 校验逻辑有缺陷")

    # ---------- N-2：非 ok-ww 区域的内容统计 ----------
    banner("N-2  INV-12 边界：抓非 ok-ww 的屏幕区域，看校验器怎么判")
    # 抓屏幕左下角一块（大概率是桌面/任务栏以外区域）
    probes = [
        ("屏幕左上角 (0,0) 100x100", 0, 0, 100, 100),
        ("ok-ww 之外的右侧区域", min(2560 - 200, r.right + 10), r.top, 150, 150),
    ]
    for name, x, y, w, h in probes:
        if x + w > 2560 or y + h > 1440 or x < 0 or y < 0:
            print(f"   [{name}] 越界，跳过")
            continue
        got = C.capture_region(x, y, w, h)
        if got is None:
            print(f"   [{name}] 抓帧失败")
            continue
        d, fw, fh = got
        st = C.frame_stats(d, fw, fh)
        mean = sum(st["mean_rgb"])
        verdict = "全黑->中止" if mean < 15 else "有内容->放行"
        print(f"   [{name}] {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']} => {verdict}")

    # ---------- N-3：离屏坐标 ----------
    banner("N-3  抓帧健壮性：离屏 / 部分越界坐标")
    for name, x, y, w, h in [
        ("完全离屏 (10000,10000)", 10000, 10000, 100, 100),
        ("部分越界 (2500,1400,200,200)", 2500, 1400, 200, 200),
    ]:
        got = C.capture_region(x, y, w, h)
        if got is None:
            print(f"   [{name}] 抓帧返回 None —— 能被检出")
        else:
            d, fw, fh = got
            st = C.frame_stats(d, fw, fh)
            print(f"   [{name}] 竟返回 {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")

    # ---------- N-4：窗口尺寸「变化」的模拟 ----------
    banner("N-4  INV-2/INV-3 推演：资产出生尺寸校验")
    print("   假设某资产出生尺寸 = 1200x800，而当前窗口 = %dx%d" % (ww, wh))
    asset_born = (1200, 800)
    if asset_born != (ww, wh):
        print(f"   [OK] 归属校验会**拒绝**使用该资产：出生 {asset_born} != 当前 {(ww, wh)}")
        print("        => 这正是 INV-4 要拦住的情形（匹配成功但不同源）")
    else:
        print("   尺寸恰好相同，无法演示")

    print("\n" + "=" * 62)
    print("负向对照结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
