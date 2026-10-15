"""orchestrator.match — 模板匹配、锚点唯一性、帧身份校验

本模块承载 ADR 0002 的识别契约：

  1. **可见锚点组合**：用「日历图标 + 每日任务文字」（`2_ww.png[:, 9:72]`）。
     单用「每日任务」四字实测有 2 个候选，且**最高分那个是错行**（0.9991 落在
     「多账号每日任务」行，对行只有 0.9225）。组合成 63px 后唯一。
  2. **联合唯一性**：不取最高分。先列全部 >= 0.85 的锚点候选，再检查每个候选的
     **同行**是否存在「开始」按钮；两个条件同时成立的候选必须恰好一个，否则拒绝。
  3. **阈值只是必要条件**：接受 >= 0.90，告警 0.85~0.90，拒绝 < 0.85。
     由于错行 0.9991 > 对行 0.9471，**不存在**能同时接受对行、拒绝错行的阈值。

另有两个辅助能力：
  - `match_best`：朴素归一化互相关（灰度），与 probe/template_probe.py 口径一致。
  - `local_maxima`：全帧所有高分位置的局部极大，唯一性检查的基础。
"""

import numpy as np

from .errors import GuardFailure

# --- 阈值（FRAMEWORK §3.4）-------------------------------------------

ACCEPT = 0.90          # >= 接受
WARN = 0.85            # 0.85~0.90 告警；唯一性检查的下限也用它
IDENTITY_MIN = 0.95    # 侧栏身份校验阈值

# 锚点：2_ww.png 的 x 范围
ANCHOR_X0, ANCHOR_X1 = 9, 72      # 日历图标 + 「每日任务」四字（ADR 0002）
CALENDAR_X0, CALENDAR_X1 = 9, 26  # 仅日历图标（实测 3 个候选，禁用）
TEXT_X0, TEXT_X1 = 35, 72         # 仅四字（实测 2 个候选，禁用）

# 侧栏图标在窗口内的稳定位置（1822x1000 帧实测 (16,215)，多次 score=1.0000）
SIDEBAR_X, SIDEBAR_Y = 16, 215
SIDEBAR_TOL = 12


def to_gray(arr):
    """(h, w, 3) uint8 -> float32 灰度。"""
    return arr.astype(np.float32).mean(axis=2)


def match_best(frame_rgb, tpl_rgb, coarse_step=4):
    """朴素归一化互相关，返回 (score, x, y)。

    先粗步长扫描、再在最优邻域细化，避免整幅 O(n*m) 过慢。无 cv2 依赖。
    """
    fh, fw = frame_rgb.shape[:2]
    th, tw = tpl_rgb.shape[:2]
    if th > fh or tw > fw:
        return None

    f = to_gray(frame_rgb)
    t = to_gray(tpl_rgb)
    t_centered = t - t.mean()
    t_norm = float(np.sqrt((t_centered ** 2).sum()))
    if t_norm == 0:
        return None

    best = (-2.0, -1, -1)
    for step in (coarse_step, 1):
        if step == coarse_step:
            xs = range(0, fw - tw + 1, step)
            ys = range(0, fh - th + 1, step)
        else:
            bx, by = best[1], best[2]
            if bx < 0:
                break
            xs = range(max(0, bx - coarse_step), min(fw - tw, bx + coarse_step) + 1)
            ys = range(max(0, by - coarse_step), min(fh - th, by + coarse_step) + 1)
        for y in ys:
            row = f[y:y + th]
            for x in xs:
                win = row[:, x:x + tw]
                wc = win - win.mean()
                wn = float(np.sqrt((wc ** 2).sum()))
                if wn == 0:
                    continue
                score = float((wc * t_centered).sum() / (wn * t_norm))
                if score > best[0]:
                    best = (score, x, y)
    return best


def score_map(frame_rgb, tpl_rgb):
    """全帧逐点相关分数矩阵。唯一性检查必须看全部位置，不能只看最大值。"""
    fh, fw = frame_rgb.shape[:2]
    th, tw = tpl_rgb.shape[:2]
    if th > fh or tw > fw:
        return None

    f = to_gray(frame_rgb)
    t = to_gray(tpl_rgb)
    tc = t - t.mean()
    tn = float(np.sqrt((tc ** 2).sum()))
    if tn == 0:
        return None

    out = np.full((fh - th + 1, fw - tw + 1), -2.0, dtype=np.float32)
    for y in range(fh - th + 1):
        row = f[y:y + th]
        for x in range(fw - tw + 1):
            win = row[:, x:x + tw]
            wc = win - win.mean()
            wn = float(np.sqrt((wc ** 2).sum()))
            if wn:
                out[y, x] = float((wc * tc).sum() / (wn * tn))
    return out


def local_maxima(sm, thresh=WARN, min_dist=30):
    """返回所有 >= thresh 的局部极大 [(y, x, score), ...]，按分数降序。

    min_dist：抑制同一目标附近的重复命中（像素级抖动会产生一串邻接高分）。
    """
    if sm is None:
        return []
    order = np.dstack(np.unravel_index(np.argsort(-sm, axis=None), sm.shape))[0]
    hits = []
    for yx in order:
        y, x = int(yx[0]), int(yx[1])
        if sm[y, x] < thresh:
            break
        if all(abs(y - yy) > min_dist or abs(x - xx) > min_dist
               for yy, xx, _ in hits):
            hits.append((y, x, float(sm[y, x])))
    return hits


def load_template(path):
    """读一张图像资产为 RGB ndarray。

    用 Pillow 时检查依赖；不可用时抛 DiscoveryFailure（由调用方转成环境错误）。
    """
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def crop_anchor(tpl_rgb):
    """裁出可见锚点组合（日历图标 + 每日任务文字）。"""
    return tpl_rgb[:, ANCHOR_X0:ANCHOR_X1]


def verify_identity(frame_rgb, sidebar_tpl):
    """身份校验（INV-12 / INV-18 / INV-23 的第一道）。

    确认这一帧**确实来自 ok-ww**：侧栏图标必须在 (16,215) 附近且分数极高。
    内容非全黑是必要条件，不是充分条件 —— 抓到别的窗口时画面同样「健康」。
    """
    res = match_best(frame_rgb, sidebar_tpl)
    if res is None:
        raise GuardFailure("INV-12", "侧栏图标模板比帧还大，无法匹配")
    score, mx, my = res
    if score < IDENTITY_MIN:
        raise GuardFailure(
            "INV-12",
            f"身份校验失败：侧栏图标 score={score:.4f} < {IDENTITY_MIN}")
    if abs(mx - SIDEBAR_X) > SIDEBAR_TOL or abs(my - SIDEBAR_Y) > SIDEBAR_TOL:
        raise GuardFailure(
            "INV-12",
            f"身份校验失败：侧栏图标位置 ({mx},{my}) 偏离预期 "
            f"({SIDEBAR_X},{SIDEBAR_Y})±{SIDEBAR_TOL}")

    # 兼容旧尺寸窗口：模板与帧同源时位置才可靠，这里只记录
    return {"score": score, "pos": (mx, my)}


def scan_row_button(frame_rgb, row_y0, row_y1):
    """在行 y 带内扫描「开始」按钮：找亮像素列簇，取**最右**者。

    交叉验证由调用方做（按钮中心 y 必须落在行范围内）。
    """
    fh, fw = frame_rgb.shape[:2]
    by0 = max(0, row_y0 - 5)
    by1 = min(fh, row_y1 + 5)
    if by1 - by0 < 6:
        return None

    band = to_gray(frame_rgb[by0:by1])
    bright = band > 200
    colsum = bright.sum(axis=0)
    cols = np.where(colsum > (by1 - by0) * 0.35)[0]
    if not len(cols):
        return None

    groups = []
    start = prev = int(cols[0])
    for c in cols[1:]:
        c = int(c)
        if c - prev > 8:
            groups.append((start, prev))
            start = c
        prev = c
    groups.append((start, prev))

    bx0, bx1 = groups[-1]
    sub = bright[:, bx0:bx1 + 1]
    rows = np.where(sub.sum(axis=1) > 3)[0]
    if not len(rows):
        return None

    cx = (bx0 + bx1) // 2
    cy = by0 + int((rows.min() + rows.max()) // 2)
    return {
        "box": (bx0, by0 + int(rows.min()), bx1, by0 + int(rows.max())),
        "center": (cx, cy),
        "groups": groups,
    }


def locate_daily_row(frame_rgb, row_tpl):
    """定位「每日任务」行，返回 {anchor, row_y0, row_y1, candidates}。

    契约（ADR 0002）：
      1. 用可见锚点组合扫描全帧 >= 0.85 的候选；
      2. 每个候选算出行 y 带，在带内找「开始」按钮；
      3. 同时满足「锚点高分」与「同行有按钮」的候选必须**恰好一个**。
    """
    anchor = crop_anchor(row_tpl)
    ah, aw = anchor.shape[:2]
    sm = score_map(frame_rgb, anchor)
    if sm is None:
        raise GuardFailure("INV-24", "锚点模板比帧还大，无法匹配")

    cands = local_maxima(sm, WARN, min_dist=max(30, aw // 2))
    if not cands:
        raise GuardFailure("INV-24", f"锚点在整帧内无 >= {WARN} 的匹配")

    best_score = cands[0][2]
    if best_score < ACCEPT:
        raise GuardFailure(
            "INV-24",
            f"锚点最高分 {best_score:.4f} < {ACCEPT}（当前页面可能不是任务页）")

    # 联合裁决：锚点候选 x 同行是否存在开始按钮
    survivors = []
    detail = []
    for y, x, score in cands:
        row_y0, row_y1 = y, y + ah
        btn = scan_row_button(frame_rgb, row_y0, row_y1)
        ok = False
        if btn:
            # 交叉验证：按钮中心 y 落在行范围内
            ok = row_y0 <= btn["center"][1] <= row_y1
        detail.append((y, x, score, bool(btn), ok))
        if ok:
            survivors.append((y, x, score, btn))

    if len(survivors) != 1:
        lines = [f"  候选({x},{y}) score={s:.4f} 同行有按钮={b} 交叉验证={c}"
                 for y, x, s, b, c in detail[:6]]
        raise GuardFailure(
            "INV-24",
            f"联合唯一性失败：{len(cands)} 个锚点候选中，"
            f"{len(survivors)} 个同时满足「同行有开始按钮」。\n"
            + "\n".join(lines))

    y, x, score, btn = survivors[0]
    return {
        "anchor": {"pos": (x, y), "score": score, "size": (aw, ah)},
        "candidates": detail,
        "row_y0": y,
        "row_y1": y + ah,
        "button": btn,
    }
