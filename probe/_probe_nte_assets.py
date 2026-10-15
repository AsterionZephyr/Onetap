# -*- coding: utf-8 -*-
"""探测：ok-nte 既有图像资产在 v1.4.14 真实帧上是否仍然有效（INV-35）。

背景：`templates/assets.json` 把 ok-nte 的资产登记为 v1.4.8 采集。
程序已升到 v1.4.14，按 INV-35「程序升级可能使图像资产过期」，
**必须实测**，不得假定有效，也不得假定失效。

用法：
    python -X utf8 probe/_probe_nte_assets.py [帧路径]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from orchestrator import match

FRAME = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "logs/shots/nte-page-00.png")
TPL = ROOT / "templates"


def scan_multi(frame, tpl, thresh=0.85, min_dist=20):
    """全帧扫描，返回所有 >= thresh 的候选（含位置）。"""
    fh, fw, _ = frame.shape
    th, tw, _ = tpl.shape
    if th > fh or tw > fw:
        return []
    f = frame.astype(np.float32).mean(axis=2)
    t = tpl.astype(np.float32).mean(axis=2)
    tc = t - t.mean()
    tn = float(np.sqrt((tc ** 2).sum()))
    if tn == 0:
        return []
    sm = np.full((fh - th + 1, fw - tw + 1), -2.0, dtype=np.float32)
    for y in range(fh - th + 1):
        row = f[y:y + th]
        for x in range(fw - tw + 1):
            win = row[:, x:x + tw]
            wc = win - win.mean()
            wn = float(np.sqrt((wc ** 2).sum()))
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
    frame = np.asarray(Image.open(FRAME).convert("RGB"))
    print(f"帧 {frame.shape[1]} x {frame.shape[0]}  ({FRAME})")

    names = ["3_nte_daily.png", "4_nte_menu.png",
             "1_ww.png", "2_ww.png", "2_ww_page.png", "3_ww_menu.png"]
    for name in names:
        p = TPL / name
        if not p.exists():
            print(f"\n[{name}] 文件不存在，跳过")
            continue
        tpl = np.asarray(Image.open(p).convert("RGB"))
        th, tw = tpl.shape[:2]
        print(f"\n[{name}] 模板 {tw}x{th}")
        got = match.match_best(frame, tpl)
        if got is None:
            print(f"  match_best 返回 None（模板 {tw}x{th} 大于帧 {frame.shape[1]}x{frame.shape[0]}，无法匹配）")
            continue
        sc, mx, my = got
        print(f"  match_best score={sc:.4f} pos=({mx},{my})")
        hits = scan_multi(frame, tpl, 0.85, max(20, tw // 2))
        print(f"  >=0.85 候选数 = {len(hits)}")
        for i, (y, x, s) in enumerate(hits[:8]):
            print(f"     [{i}] score={s:.4f} pos=({x},{y})")

        if name == "3_nte_daily.png" and sc >= 0.85:
            crop = frame[max(0, my - 6):my + th + 6, max(0, mx - 6):mx + tw + 6]
            out = ROOT / "logs/shots/nte-daily-hit.png"
            Image.fromarray(crop).save(out)
            print(f"  落盘 {out}")


if __name__ == "__main__":
    main()
