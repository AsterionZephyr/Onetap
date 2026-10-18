# -*- coding: utf-8 -*-
r"""自检：MaaEnd 绿色「开始任务」按钮（左侧带播放三角）定位器（match 模块的 zmd_* 三件套）。

只读 + 离线：只用 Pillow + numpy，不抓屏、不点鼠标、不碰目标程序。

四个用例（与任务书 a/b/c/d 一一对应）：
  a) 正例：参考帧 logs/probe/zmd_full.png。实测按钮 box=(744,772,856,812)、
     中心 (800,792)。断言 box 四边与中心都落在 ±6px 内。
  b) 负例：只保留帧上部 y<0.8H 的裁剪 —— 按钮已经不在画面里，必须**抛**
     GuardFailure，而不是返回一个凑出来的坐标。
  c) 平移例：把按钮区块整体平移 (+50,-40)（源块用背景色 (243,244,244) 涂掉），
     定位中心必须**随之平移**。这是「没有硬编码坐标」的证据 —— 读代码远不如
     跑一次有说服力。
  d) 全帧连通域清单 + 每个被拒的原因（右侧绿色胶囊、左侧勾选小圆点为什么不算）。

附加负例（不在任务书里，但每一条都对应一个会**静默点错**的失效模式）：
  - 纯色绿块（无白字）：几何尺寸全对，白字闸门必须拒（否则会点进度条/状态灯）
  - 两个同款按钮：唯一性闸门必须拒（INV-24，否则点哪个靠运气）
  - 全黑帧：一个绿连通域都没有，必须拒（INV-17 抓帧越界会产出全黑帧）

用法：
    & D:\WORKs\Anaconda\python.exe probe\zmd_locate_selfcheck.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from orchestrator import match
from orchestrator.errors import GuardFailure

# 本机控制台是 GBK(936)：脚本里有 ±/≥/≈ 之类的符号时，默认 stdout 会在 print
# 阶段抛 UnicodeEncodeError，让自检「假失败」（实测踩过一次，指纹是 gbk codec
# can't encode '\xb2'）。把错误策略改成 replace —— 宁可有字符显示成 ?，
# 也不能让编码问题把断言结果带走。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

# 参考帧放进 fixtures/ 一起提交（logs/ 被 .gitignore 忽略，新克隆的仓库里没有它，
# 自检就会「跑不起来」而不是「跑失败」—— 后者至少会报错）。
FRAME = ROOT / "probe/fixtures/zmd_full.png"
if not FRAME.exists():
    FRAME = ROOT / "logs/probe/zmd_full.png"
# 实测事实（2026-10-18，1201x826 整窗帧）：半开区间 box + 中心
EXPECT_BOX = (744, 772, 856, 812)
EXPECT_CENTER = (800, 792)
TOL = 6                       # 允许误差：step=4 降采样的边界量化 ±3px，留到 6
BG = (243, 244, 244)          # 实测页面背景色，涂掉源块用
FAILS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}{(' —— ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)
    return cond


def hr(title):
    print()
    print("=" * 72)
    print(title)


def near(a, b, tol=TOL):
    return all(abs(int(x) - int(y)) <= tol for x, y in zip(a, b))


def reason_of(lines, box):
    """在 zmd_locate_start 的拒绝日志里找出某个 box 的拒因行。"""
    key = f"box={tuple(box)}"
    for ln in lines:
        if key in ln and "拒绝" in ln:
            return ln.strip()
    return None


def main():
    hr("[0] 环境 / 基本契约")
    if not FRAME.exists():
        print(f"  [SKIP] 缺少参考帧 {FRAME}")
        return 2
    im = np.asarray(Image.open(FRAME).convert("RGB"))
    H, W = im.shape[:2]
    print(f"  参考帧 {W}x{H} RGB <- {FRAME.relative_to(ROOT)}")
    check("帧尺寸 1201x826", (W, H) == (1201, 826), f"实际 {W}x{H}")

    mask = match.zmd_green_mask(im)
    check("zmd_green_mask 返回 bool 的 HxW",
          mask.dtype == np.bool_ and mask.shape == (H, W),
          f"dtype={mask.dtype} shape={mask.shape}")
    n_green = int(mask.sum())
    check("全帧绿像素在 7000..9000（实测 8013）", 7000 <= n_green <= 9000, f"实际 {n_green}")

    # uint8 相减会回绕（0-255 变 1），把浅灰背景整片判成绿。必须用 int16 算。
    bg8 = np.full((8, 8, 3), BG, dtype=np.uint8)
    check("背景色 (243,244,244) 不算绿（防 uint8 相减回绕）",
          int(match.zmd_green_mask(bg8).sum()) == 0)
    main_green = np.full((8, 8, 3), (0, 139, 69), dtype=np.uint8)
    check("主色 (0,139,69) 算绿", bool(match.zmd_green_mask(main_green).all()))

    comps = match.zmd_components(mask)
    check("连通域按 cells 降序",
          all(comps[i]["cells"] >= comps[i + 1]["cells"] for i in range(len(comps) - 1)),
          f"共 {len(comps)} 个")
    check("最大连通域就是按钮 box", comps[0]["box"] == EXPECT_BOX, f"{comps[0]['box']}")

    # ---------------------------------------------------------------- a)
    hr("[1] (a) 正例：参考帧上定位「开始任务」")
    t0 = time.perf_counter()
    loc = match.zmd_locate_start(im)
    dt = (time.perf_counter() - t0) * 1000
    box = loc["button"]["box"]
    ctr = loc["button"]["center"]
    print(f"  定位 box={box} center={ctr} area={loc['button']['area']} "
          f"frame_size={loc['frame_size']}（{dt:.0f} ms）")
    print(f"  candidates {len(loc['candidates'])} 个（只含过了几何闸门的块）：")
    for c in loc["candidates"]:
        print(f"    box={c['box']} area={c['area']:6d} 白占比={c['white_frac']:.4f}")
    check("box 四边都在预期 ±6px 内", near(box, EXPECT_BOX), f"{box} vs {EXPECT_BOX}")
    check("center 在预期 ±6px 内", near(ctr, EXPECT_CENTER), f"{ctr} vs {EXPECT_CENTER}")
    check("frame_size 与输入帧一致", loc["frame_size"] == (W, H), f"{loc['frame_size']}")
    check("area 单位 = cells*step^2（275*16=4400）",
          loc["button"]["area"] == comps[0]["cells"] * match.ZMD_COMP_STEP ** 2,
          f"area={loc['button']['area']} cells={comps[0]['cells']}")

    # ---------------------------------------------------------------- b)
    hr("[2] (b) 负例：只保留 y<0.8H 的上半帧（按钮已被裁掉）")
    top = im[: int(H * 0.8)].copy()
    print(f"  输入帧 {top.shape[1]}x{top.shape[0]}（按钮 y=772..812 不在其中），"
          f"底部带 y >= {int(top.shape[0] * match.ZMD_BOTTOM_FRAC)}")
    try:
        bad = match.zmd_locate_start(top)
        check("必须抛 GuardFailure", False,
              f"却返回 box={bad['button']['box']}（这就是静默点错）")
    except GuardFailure as e:
        check("必须抛 GuardFailure", True, f"INV={e.invariant}")
        check("INV 码是 INV-24", e.invariant == "INV-24", e.invariant)
        print(f"    拒因首行：{e.detail.splitlines()[0]}")

    # ---------------------------------------------------------------- c)
    hr("[3] (c) 平移例：按钮整体平移 (+50,-40)，定位必须跟着走")
    dx, dy = 50, -40
    x0, y0, x1, y1 = EXPECT_BOX
    bw, bh = x1 - x0, y1 - y0
    src = im[y0:y1, x0:x1].copy()
    moved = im.copy()
    moved[y0:y1, x0:x1] = BG            # 源块涂背景色，确保原处不再有绿
    nx0, ny0 = x0 + dx, y0 + dy
    moved[ny0:ny0 + bh, nx0:nx0 + bw] = src
    check("源位置已无绿像素", int(match.zmd_green_mask(moved)[y0:y1, x0:x1].sum()) == 0)
    loc2 = match.zmd_locate_start(moved)
    b2, c2 = loc2["button"]["box"], loc2["button"]["center"]
    print(f"  平移后 box={b2} center={c2}（源块粘到 ({nx0},{ny0})）")
    check("平移后 box 起点 ≈ (794,732)（step=4 量化 ±6px）",
          near((b2[0], b2[1]), (nx0, ny0)), f"{b2}")
    shift = (c2[0] - ctr[0], c2[1] - ctr[1])
    check(f"中心平移量 ≈ ({dx:+d},{dy:+d})", near(shift, (dx, dy)),
          f"实际 ({shift[0]:+d},{shift[1]:+d}) —— 坐标未硬编码")

    # ---------------------------------------------------------------- d)
    hr("[4] (d) 全帧所有绿色连通域 + 被滤掉的原因")
    logs = []
    match.zmd_locate_start(im, log=logs.append)
    for ln in logs:
        print(ln)
    print(f"  —— 共 {len(comps)} 个连通域，日志 {len(logs)} 行")
    r_pill = reason_of(logs, (1032, 132, 1116, 156))
    r_dot = reason_of(logs, (64, 164, 84, 184))
    check("右侧「电脑端前台」绿胶囊 (1032,132,1116,156) 被拒",
          r_pill is not None, r_pill or "未出现在拒绝清单")
    check("  拒因是高 24 太矮", bool(r_pill and "高 24" in r_pill))
    check("左侧勾选小圆点 (64,164,84,184) 被拒",
          r_dot is not None, r_dot or "未出现在拒绝清单")
    check("  拒因是格数 23 太小", bool(r_dot and "格数 23" in r_dot))

    # ---------------------------------------------------------------- 附加
    hr("[5] 附加负例：每一种都会导致「静默点错」")
    solid = im.copy()
    solid[y0:y1, x0:x1] = (0, 139, 69)          # 同位置、同尺寸，但抹掉白字
    try:
        r = match.zmd_locate_start(solid)
        check("纯色绿块（无白字）必须被拒", False,
              f"却返回 box={r['button']['box']}（会点在进度条/状态灯上）")
    except GuardFailure as e:
        check("纯色绿块（无白字）必须被拒", True, f"INV={e.invariant}")
        check("  拒因是白占比", "白占比" in e.detail, e.detail.splitlines()[0][:70])

    dup = im.copy()
    dup[760:760 + bh, 300:300 + bw] = src       # 第二个同款按钮，同处底部带
    try:
        r = match.zmd_locate_start(dup)
        check("两个同款绿按钮必须被拒（INV-24 唯一性）", False,
              f"却返回 box={r['button']['box']}")
    except GuardFailure as e:
        check("两个同款绿按钮必须被拒（INV-24 唯一性）", True, f"INV={e.invariant}")
        check("  拒因是唯一性", "唯一性" in e.detail, e.detail.splitlines()[0][:70])

    try:
        match.zmd_locate_start(np.zeros((H, W, 3), dtype=np.uint8))
        check("全黑帧必须被拒", False, "却通过了")
    except GuardFailure as e:
        check("全黑帧必须被拒", True, f"INV={e.invariant}")

    hr("汇总")
    if FAILS:
        print(f"  FAILED ({len(FAILS)}): {FAILS}")
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
