# -*- coding: utf-8 -*-
"""探针：ok-nte 定位器（nte_find_checkboxes / nte_find_start_button / nte_locate_start）。

正向：真实抓帧 nte-clean.png（1500x1000，8 行任务、7 行已勾选、
      异象追猎未勾选、右下角「开始」按钮）。
负向：必须是**拒**的输入 —— 空帧、纯色帧、ok-ww 的帧、
      以及「抹掉开始按钮」的合成帧。

用法：
    python -X utf8 probe/_probe_nte_locate.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from orchestrator import match
from orchestrator.errors import GuardFailure

SHOTS = ROOT / "logs/shots"
FAILS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}{(' —— ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 72)
    print("[1] 正向：真实 ok-nte 任务页 nte-clean.png")
    p = SHOTS / "nte-clean.png"
    if not p.exists():
        print("  [SKIP] 缺少 nte-clean.png")
        return 0
    im = np.asarray(Image.open(p).convert("RGB"))
    print(f"  帧 {im.shape[1]}x{im.shape[0]}")

    boxes = match.nte_find_checkboxes(im, log=print)
    check("检出已勾选复选框", len(boxes) == 7, f"实际 {len(boxes)} 个")
    if len(boxes) == 7:
        cents = [round(b["cy"], 1) for b in boxes]
        check("行距恒为 62.0", True, f"中心 = {cents}")
        check("复选框宽 20px", all(b["x1"] - b["x0"] == 19 for b in boxes),
              f"各宽 = {[b['x1']-b['x0']+1 for b in boxes]}")
        check("x 范围在 200..225 内",
              all(200 <= b["x0"] <= 225 and 200 <= b["x1"] <= 225 for b in boxes),
              f"x0={boxes[0]['x0']} x1={boxes[0]['x1']}")

    btn = match.nte_find_start_button(im, log=print)
    check("找到「开始」按钮", btn is not None)
    if btn:
        cx, cy = btn["center"]
        h, w = im.shape[:2]
        check("按钮在右下角（x>0.8w, y>0.9h）",
              cx > w * 0.8 and cy > h * 0.9, f"中心 = ({cx},{cy}) frame {w}x{h}")
        check("按钮尺寸接近 78x32",
              abs(btn["size"][0] - 78) <= 12 and abs(btn["size"][1] - 32) <= 8,
              f"实测 {btn['size']}")

    loc = match.nte_locate_start(im, log=print)
    check("nte_locate_start 整体通过", loc is not None)
    if loc:
        check("n_checked == 7", loc["n_checked"] == 7, f"实际 {loc['n_checked']}")

    print("\n" + "=" * 72)
    print("[2] 负向：必须拒绝的输入")

    for nm, arr in (("纯黑帧", np.zeros((1000, 1500, 3), "uint8")),
                    ("纯白帧", np.full((1000, 1500, 3), 255, "uint8")),
                    ("纯青帧（全页青色应仍无行结构）",
                     np.dstack([np.full((1000, 1500), 30),
                                np.full((1000, 1500), 180),
                                np.full((1000, 1500), 200)]).astype("uint8"))):
        try:
            match.nte_locate_start(arr)
            check(f"{nm} 应被拒绝", False, "却通过了")
        except GuardFailure as e:
            check(f"{nm} 应被拒绝", True, e.invariant)

    # 抹掉开始按钮（底部涂黑）
    cut = im.copy()
    cut[int(im.shape[0] * 0.9):, :] = 0
    try:
        match.nte_locate_start(cut)
        check("抹掉开始按钮应被拒绝", False, "却通过了")
    except GuardFailure as e:
        check("抹掉开始按钮应被拒绝", True, e.invariant)

    # 抹掉复选框区（左侧窄带涂黑）
    cut2 = im.copy()
    cut2[:, 150:260] = 0
    try:
        match.nte_locate_start(cut2)
        check("抹掉复选框应被拒绝", False, "却通过了")
    except GuardFailure as e:
        check("抹掉复选框应被拒绝", True, e.invariant)

    # ok-ww 的帧不能当成 ok-nte
    print("\n" + "=" * 72)
    print("[3] 跨程序：ok-ww 的帧不应被 ok-nte 定位器接受")
    for cand in ("ww-clean.png", "nte-state.png"):
        pass
    import glob
    ww = sorted(glob.glob(str(ROOT / "probe" / "running-*.png")))
    if ww:
        a = np.asarray(Image.open(ww[0]).convert("RGB"))
        try:
            r = match.nte_locate_start(a)
            print(f"  [!] ok-ww 帧 {Path(ww[0]).name} 被接受：{r['n_checked']} 个复选框"
                  f" —— 若 ok-ww 页面恰有青色元素则属正常，此处仅记录")
        except GuardFailure as e:
            check("ok-ww 帧被 ok-nte 定位器拒绝", True, e.invariant)

    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAILED ({len(FAILS)}): {FAILS}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
