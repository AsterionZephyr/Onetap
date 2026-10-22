"""orchestrator.selftest — 用已落盘的帧离线自测识别链（只读）

为什么需要它：「实跑」会真的点下去，而识别链的失败模式**大多是静默的**
（HANDOFF.md §6 第 2 条：一个从不报错的校验器等于没有校验器）。
本模块用历史帧跑识别链，并**故意喂坏帧**验证校验器真的会失败。

    python -m orchestrator.selftest                      # 用内置样本帧
    python -m orchestrator.selftest <frame.png> [...]     # 用指定帧
"""

import os
import sys

import numpy as np

from . import assets as assets_mod
from . import capture, match
from .errors import GuardFailure

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 内置样本帧（仓库内已存在，均为 1823x1000 或 1875x1250 的任务页）
SAMPLES = [
    ("任务页（面板展开）", os.path.join(ROOT, "probe", "running-000.png")),
    ("任务页（面板展开·另一尺寸）", os.path.join(ROOT, "probe", "obs-000.png")),
    ("首页（非任务页）", os.path.join(ROOT, "probe", "okww-now.png")),
]


def load_rgb(path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    return np.asarray(im)


def check_identity(frame_rgb, registry):
    sidebar = registry["sidebar_tasks"].load()
    try:
        ident = match.verify_identity(frame_rgb, sidebar)
        return True, f"score={ident['score']:.4f} pos={ident['pos']}"
    except GuardFailure as e:
        return False, f"{e.invariant}: {e.detail}"


def check_row(frame_rgb, registry):
    row_tpl = registry["daily_row"].load()
    try:
        loc = match.locate_daily_row(frame_rgb, row_tpl)
        a = loc["anchor"]
        return True, (f"锚点 score={a['score']:.4f} pos={a['pos']}  "
                      f"候选数={len(loc['candidates'])}  "
                      f"行 y={loc['row_y0']}..{loc['row_y1']}  "
                      f"按钮中心={loc['button']['center']}")
    except GuardFailure as e:
        return False, f"{e.invariant}: {e.detail.splitlines()[0]}"


def negative_controls(registry):
    """负向对照：证明校验器**真的会失败**（HANDOFF.md §6 第 2 条）。"""
    print("\n" + "=" * 78)
    print("负向对照（一个从不报错的校验器等于没有校验器）")
    print("=" * 78)

    frame_path = SAMPLES[0][1]
    if not os.path.isfile(frame_path):
        print("  跳过：样本帧不存在")
        return
    rgb = load_rgb(frame_path)
    h, w = rgb.shape[:2]

    # N-1：把图像上下翻转 —— 侧栏图标跑到下方，身份校验必须失败
    flipped = np.ascontiguousarray(rgb[::-1])
    ok, detail = check_identity(flipped, registry)
    print(f"\n[N-1] 输入上下翻转的帧（侧栏图标不在原位）")
    print(f"      身份校验 = {'通过' if ok else '失败'}  {detail}")
    print(f"      期望：失败。实际：{'通过 —— 校验器有漏洞！' if ok else '失败 [OK]'}")

    # N-2：纯黑帧 —— 内容校验必须失败（INV-13）
    print(f"\n[N-2] 输入纯黑帧")
    try:
        stats = capture.frame_stats(b"\x00" * (w * h * 4), w, h)
        mean_sum = sum(stats["mean_rgb"])
        verdict = "失败" if mean_sum < capture.MIN_MEAN_SUM else "通过"
        print(f"      均值RGB={stats['mean_rgb']} 阈值={capture.MIN_MEAN_SUM}")
        print(f"      内容校验 = {verdict}  "
              f"期望：失败。实际：{'通过 —— 校验器有漏洞！' if verdict == '通过' else '失败 [OK]'}")
    except Exception as e:
        print(f"      异常：{e}")

    # N-3：把「仅四字」当锚点 —— 应当暴露歧义（ADR 0002 的证据）
    print(f"\n[N-3] 用被否决的「仅每日任务四字」当锚点（ADR 0002 的证据）")
    tpl = registry["daily_row"].load()
    text_only = tpl[:, match.TEXT_X0:match.TEXT_X1]
    sm = match.score_map(rgb, text_only)
    hits = match.local_maxima(sm, match.WARN, min_dist=30)
    print(f"      候选数 = {len(hits)}  " +
          "  ".join(f"{s:.4f}@({x},{y})" for y, x, s in hits[:4]))
    print(f"      期望：>=2（歧义）。实际：{'歧义 [OK]' if len(hits) >= 2 else '唯一 —— 与 ADR 0002 记录不符'}")

    # N-4：整行匹配 —— 应当暴露「空白区不设约束」（INV-19）
    print(f"\n[N-4] 用整行模板匹配（INV-19：空白区不设约束力）")
    res = match.match_best(rgb, tpl)
    if res:
        score, x, y = res
        print(f"      整行 score={score:.4f} @ ({x},{y})")
    else:
        print("      整行模板比帧还大，无法匹配（本身也是一种拒绝）")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    registry = assets_mod.Registry()

    print("=" * 78)
    print("orchestrator 识别链自测（只读，不点击）")
    print("=" * 78)
    print("\n[图像库]")
    print(registry.report())

    targets = []
    if argv:
        targets = [(os.path.basename(p), p) for p in argv]
    else:
        targets = [(name, p) for name, p in SAMPLES if os.path.isfile(p)]

    if not targets:
        print("\n没有可用的样本帧。用法：python -m orchestrator.selftest <frame.png>")
        return 2

    print("\n" + "=" * 78)
    print("识别链")
    print("=" * 78)

    for name, path in targets:
        rgb = load_rgb(path)
        h, w = rgb.shape[:2]
        print(f"\n--- {name}  {w}x{h}  ({os.path.basename(path)})")
        ok_id, detail_id = check_identity(rgb, registry)
        print(f"    身份校验 : {'通过' if ok_id else '失败'}  {detail_id}")
        ok_row, detail_row = check_row(rgb, registry)
        print(f"    行定位   : {'通过' if ok_row else '失败'}  {detail_row}")

    negative_controls(registry)

    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
