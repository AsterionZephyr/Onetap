"""ww_action.py — ok-ww 的动作元素定位（行结构扫描）

ok-ww 的「开始」按钮不是固定模板，而是「每日任务」行末端的元素，
由行结构扫描得出（见 run_daily2.py 与 HISTORY A.5 实测三）。

把它抽成函数，供编排层调用。
"""

import numpy as np

from template_probe import match_template
import targets as T


def find_ww_action(frame):
    """返回 (ok, (cx, cy), score, row_y0, row_y1, detail)。

    步骤：
      1. 用「每日任务」四字锚点定位该行（须唯一）
      2. 在同一 y 带内扫描高亮按钮块，取最右者
      3. 交叉验证：按钮中心 y 必须落在行范围内
    """
    anchor = T.WW_PAGE_ANCHOR
    ok_p, hits = T.unique(frame, anchor, T.ACCEPT)
    if not hits:
        return False, None, 0.0, 0, 0, "页面锚点未命中"
    if not ok_p:
        return False, None, 0.0, 0, 0, f"页面锚点不唯一（{len(hits)}）"

    ay, ax, asc = hits[0]
    th, tw, _ = anchor.shape
    row_y0, row_y1 = ay, ay + th
    return _scan_row_button(frame, row_y0, row_y1, asc, mode="white")


def find_nte_action(frame):
    """ok-nte v1.4.8+ 的动作元素定位（行结构扫描）。

    背景：**v1.4.8 起 ok-nte 的 UI 改版** —— 原先"单行「日常任务」+ 右下角一个「开始」"
    变成**逐任务行**（每行一个「开始」按钮，与 ok-ww 同构）。
    故不能再靠固定按钮模板（实测有 9 个同款按钮，必然歧义），改用行结构扫描。

    与 ok-ww 的区别：ok-nte 的按钮是**青色**（背景高亮），ok-ww 是白色。
    """
    anchor = T.NTE_PAGE
    ok_p, hits = T.unique(frame, anchor, T.ACCEPT)
    if not hits:
        return False, None, 0.0, 0, 0, "页面锚点未命中"
    if not ok_p:
        return False, None, 0.0, 0, 0, f"页面锚点不唯一（{len(hits)}）"

    ay, ax, asc = hits[0]
    th, tw, _ = anchor.shape
    row_y0, row_y1 = ay, ay + th
    return _scan_row_button(frame, row_y0, row_y1, asc, mode="cyan")


def _scan_row_button(frame, row_y0, row_y1, asc, mode="white"):
    """在给定 y 带内扫描按钮块，取最右者并做交叉验证。

    ⚠️ 实测教训（INV-41）：列阈值**不能按"带高的比例"取**。
    带高 = 行高 + 上下各 5px；而按钮是**描边盒子**，实心亮像素只占
    其中约 14px（实测 1823x1000 下按钮亮列计数峰值 = 14）。
    旧实现要求 `> 带高*0.35`（=17.5）**永远无法满足**，于是报"未找到按钮块"。
    ⇒ 改为：阈值取 `带高*0.35` 与 `按钮预期高*0.5` 的**较小者**，
      并加一个绝对下限，避免在小尺寸下退化。
    """
    fh, fw = frame.shape[:2]
    by0, by1 = max(0, row_y0 - 5), min(fh, row_y1 + 5)
    band_h = by1 - by0
    band = frame[by0:by1].astype(np.float32)

    if mode == "cyan":
        # 青色高亮按钮：B/G 高、R 低（实测按钮底色）
        r_, g_, b_ = band[:, :, 0], band[:, :, 1], band[:, :, 2]
        mask = (b_ > 150) & (g_ > 150) & (r_ < 130)
    else:
        mask = band.mean(axis=2) > 200

    colsum = mask.sum(axis=0)
    if not colsum.any():
        return False, None, 0.0, row_y0, row_y1, "该行未找到按钮块"

    # 阈值：带高的 35% 偏高，改用"峰值的一半"更稳健（实测峰值 14 -> 阈值 7）
    peak = int(colsum.max())
    thr = max(3, min(int(band_h * 0.35), peak // 2))
    cols = np.where(colsum > thr)[0]
    if not len(cols):
        return False, None, 0.0, row_y0, row_y1, \
            f"该行未找到按钮块（峰值列计数={peak}，阈值={thr}）"

    groups = []
    s = prev = cols[0]
    for c in cols[1:]:
        if c - prev > 8:
            groups.append((s, prev)); s = c
        prev = c
    groups.append((s, prev))
    bx0, bx1 = groups[-1]          # 取最右者
    bcx = (bx0 + bx1) // 2

    sub_b = mask[:, bx0:bx1 + 1]
    rows = np.where(sub_b.sum(axis=1) > 3)[0]
    if not len(rows):
        return False, None, 0.0, row_y0, row_y1, "按钮块无有效行"
    bcy = by0 + (rows.min() + rows.max()) // 2

    if not (row_y0 - 5 <= bcy <= row_y1 + 5):
        return False, None, 0.0, row_y0, row_y1, \
            f"交叉验证失败：按钮 y={bcy} 不在行 {row_y0}..{row_y1}"

    return True, (bcx, bcy), float(asc), row_y0, row_y1, \
        f"按钮 x={bx0}..{bx1}，行 y={row_y0}..{row_y1}（{mode}，峰值={peak}）"

