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

# ---------------------------------------------------------------------------
# 身份锚点：程序化 ☰ 检测（FRAMEWORK §4.4 / INV-38）
#
# 为什么不再用 SIDEBAR_X/SIDEBAR_Y=(16,215) + 1_ww.png 作身份锚点：
#   该坐标是**绝对值**（取自 1822x1000），窗口一换尺寸必然失配 ——
#   实测 1458x800（出现过的最小尺寸）下只得 0.3962，
#   且该尺寸下 ☰ 实际在 y≈58-69，与 215 差 146px。
#   窗口还是**非等比缩放**（1458/1875=0.7776 vs 800/1250=0.6400），
#   故「按比例换算坐标」也不成立。
#   另据 INV-34，1_ww.png 本身并非按其声称位置原位裁剪：
#   参考帧 (16,215) 处裁出的 27x31 与模板逐像素不同（837 像素差 757 个），
#   且该处实际内容是「每日任务」文字区而非 ☰ ——
#   它能在参考帧上打出 1.0000 属 ZNCC 对低结构图案的假阳性。
#
# ☰ 是**窗口固定元素、页面无关**，且可用**结构性特征**定位而不依赖任何截图：
#   三条等距水平亮线。这样天然免疫 INV-38（程序启动后异步加载用户头像，
#   左上角像素随之改变，同一 ☰ 模板可从 1.0000 掉到 0.55）。
# ---------------------------------------------------------------------------

MENU_SCAN_W = 80           # ☰ 只可能在窗口左上角这一窄条内
MENU_SCAN_H = 160
MENU_MIN_ROW_PIX = 6       # 单条横线至少这么长的亮像素
MENU_BRIGHT = 140          # 亮线灰度阈值
MENU_LINES = 3             # ☰ 恰有 3 条横线
MENU_BARWH_RATIO = 0.10    # 线宽 / 线长 的容差上限
# 等距性：真 ☰ 实测**完全等距**（1458x800 为 5.0/5.0，1875x1250 为 6.5/6.5，
# 偏差均为 0），故容差必须收紧。曾取 0.45 —— 那等于几乎不设防：
# 实测「三线不等距（间距 5.0 与 11.0）」的合成帧能蒙混过关（score 仅 0.167）。
MENU_GAP_TOL = 0.12        # 相邻间距的相对偏差上限
MENU_MIN_SCORE = 0.5       # 等距性评分下限（防低分候选过关）
# ☰ 必须落在窗口左上角。**用相对比例，不用绝对坐标** ——
# 实测尺寸跨 1458x800 ~ 2560x1400，绝对坐标在某个尺寸上必然错（INV-39）。
# 参考实测：1458x800 → (17,56)；1875x1250 / 1822x1000 / 1500x1000 → (21,71)。
MENU_CORNER_W_FRAC = 0.06  # 窗口宽度的 6%
MENU_CORNER_H_FRAC = 0.12  # 窗口高度的 12%

# --- ☰ 的「左内边距」判据（负向对照 N-1 逼出来的）-----------------------
# 上面 MENU_CORNER_*_FRAC 只约束「在左上角」这个**粗**事实，不足以排除
# 「左上角里恰好也有三条等距同长亮线」的干扰项。实测反例（selftest N-1）：
#   把 1875x1250 帧**上下翻转**后，☰ 被翻到画面底部，
#   但左上角残留侧栏第二项图标翻转后的形状，在 y=126/129/132 处
#   给出三行 x=67..77 一字不差的线、间距 3.0/3.0 —— 完美满足等距+同起同长，
#   于是身份校验**误判通过**（score=1.0）。一个从不报错的校验器等于没有校验器。
#
# 四张真 ok-ww 帧（三种尺寸）实测 ☰ 的横向几何：
#   1875x1250  x=21..39  len=19  gap=6.5  右边缘/宽=0.0208
#   1822x1000  x=21..39  len=19  gap=6.5  右边缘/宽=0.0214
#   1500x1000  x=21..39  len=19  gap=6.5  右边缘/宽=0.0260
#   1458x800   x=17..31  len=15  gap=5.0  右边缘/宽=0.0213
# ⇒ ☰ 是**贴着窗口左内边距**的固定布局元素：尺寸变 1.29 倍，右边缘占比
#   **恒在 0.021~0.026**（内边距是布局常量，不随窗口缩放）。
# 而翻转帧的干扰项右边缘占比 0.0411 —— 是它的 1.6~2.0 倍，明显在带外。
MENU_X1_FRAC = 0.030       # ☰ 右边缘不得超过窗口宽度的 3.0%（真值<=0.026）
# 横向尺寸下限：真 ☰ 最短也来自最小窗口 1458x800 的 len=15 / gap=5.0。
# 翻转帧干扰项 len=11 / gap=3.0。取 4px 作间距下限（真值 >=5.0，干扰 3.0）。
# 注意：**不能**用 len>=13 这类绝对像素阈值 —— 它和 (16,215) 是同一类错误，
# 在更小窗口上必然误杀。故只保留 gap 下限，长度交给下面的比例判据。
MENU_MIN_GAP = 4.0         # 相邻两线的像素间距下限

# --- 侧栏菜单项定位（FAULT #11 逼出来的）--------------------------------
# 背景：导航点击目标曾经**复用了身份锚点的 pos**：
#     ident = verify_identity(frame, tpl); cx = ident["pos"][0] + tw // 2; ...
# 改造前身份锚点就是侧栏「任务」图标，故这个复用恰好成立；
# 改成 ☰ 检测后，pos 变成 ☰ 的位置 ⇒ **导航点到了 ☰**，
# 页面永远停在原处（实测连点 3 次，ok-ww 一直停在「关于」页）。
# 教训：`1_ww.png` 曾同时承担「身份锚点 + 导航目标」两个职责，
#       改掉其中一个却沿用了另一个的返回值 ⇒ 静默错点（不报错，只点错地方）。
#
# 正确做法（FRAMEWORK.md:433）：导航目标**程序化定位**，不用截图模板。
# 侧栏项是「图标 + 文字」垂直排列、**行距均匀**。实测 1458x800：
#     截图方式 y=101 / 实时触发 141 / 任务 190 / 角色代码 223 / 脚本 261
#     / 模板 300 / 计划任务 340 / 角色设置 385 / 游戏快捷键 421
# 行距 ~40px（96→136→176→216→256→296→336→376→418），且**顶部第一项
# 与 ☰ 之间必然隔着标题栏/头像** ⇒ 用「☰ 之下第一个等距项簇」定序，
# 再按**序号**取目标项，绝不用绝对 y（INV-39：尺寸变则 y 变）。
SIDEBAR_SCAN_H_FRAC = 0.80  # 侧栏文字带扫到窗口高度的这个比例
SIDEBAR_TEXT_X0, SIDEBAR_TEXT_X1 = 8, 95   # 侧栏文字/图标的横向范围
SIDEBAR_TEXT_THR = 110      # 文字亮像素灰度阈值
SIDEBAR_MIN_PIX = 2         # 一行至少这么多亮像素才算文字
SIDEBAR_GAP = 2             # 行合并容差
SIDEBAR_PITCH_TOL = 0.35    # 相邻项行距的相对偏差上限（判「等距列表」）
SIDEBAR_MIN_ITEMS = 3       # 至少这么多项才认作侧栏列表
# 侧栏各项的**序号**（0-based）。取自实测：截图方式=0 实时触发=1 **任务=2**。
SIDEBAR_ITEM_TASKS = 2

# 旧口径保留作**回退**（FRAMEWORK §4.4 三层策略的第三层）
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


def find_menu_glyph(frame_rgb, log=None):
    """程序化定位左上角 ☰ 菜单图标（主页无关的窗口固定元素）。

    判据（同时成立，见 FRAMEWORK §4.4 的「三条等距水平亮线」）：
      1. 在左上窄条内取**滑窗**，存在**连续三条**够长的水平亮线；
         （不可要求「全局恰好三条」—— 该区域必然混入标题栏文字、异步加载的头像
           与侧栏首个菜单项图标；实测 ok-ww 1458x800 在此有 11 条候选线）
      2. 三条线**等距**（相邻间距的相对偏差 <= MENU_GAP_TOL）；
      3. 三条线**同起同长** —— ☰ 是齐整的三横。这是最强判据：
         实测真 ☰ 三行是 x=17..31 一字不差，而干扰项总是长度不一/起点漂移。

    返回 {"pos": (x, y), "bbox": (x0,y0,x1,y1), "centers": [...], "score": s}
    或 None。score 是等距性评分（1 = 完美等距），语义上对应旧口径的匹配分数。
    """
    h, w = frame_rgb.shape[:2]
    x1 = min(w, MENU_SCAN_W)
    y1 = min(h, MENU_SCAN_H)
    if x1 < 8 or y1 < 8:
        return None

    g = to_gray(frame_rgb[:y1, :x1])
    bright = g > MENU_BRIGHT

    bars = []                                  # 每行的亮像素区间
    for y in range(y1):
        xs = np.where(bright[y])[0]
        if len(xs) < MENU_MIN_ROW_PIX:
            continue
        # 只取最长的一段连续亮像素（防把同行别的元素算进来）
        splits = np.where(np.diff(xs) > 1)[0]
        runs = np.split(xs, splits + 1)
        run = max(runs, key=len)
        if len(run) < MENU_MIN_ROW_PIX:
            continue
        bars.append((y, int(run[0]), int(run[-1])))

    if len(bars) < MENU_LINES:
        return None

    # 相邻行合并成「一条线」，取其中最长的那个 run 作为该线几何
    groups = []
    cur = [bars[0]]
    for b in bars[1:]:
        if b[0] - cur[-1][0] <= 1:
            cur.append(b)
        else:
            groups.append(cur)
            cur = [b]
    groups.append(cur)

    geom = []
    for gp in groups:
        _, bx0, bx1 = max(gp, key=lambda t: t[2] - t[1])
        cy = sum(t[0] for t in gp) / len(gp)
        geom.append((cy, bx0, bx1))
    geom.sort(key=lambda t: t[0])

    # 注意：**不能**要求「全局恰好 3 条线」。左上窄条内必然混入标题栏文字、
    # 异步加载的头像、以及侧栏第一个菜单项的图标，它们都会产生够长的亮线
    # （实测 ok-ww 1458x800 在此区域有 11 条）。故改为**滑窗聚类**：
    # 只需存在「连续三条」满足等距 + 同起同长即可。
    best = None
    for i in range(len(geom) - MENU_LINES + 1):
        trio = geom[i:i + MENU_LINES]
        centers = [c for c, _, _ in trio]
        starts = [b0 for _, b0, _ in trio]
        ends = [b1 for _, _, b1 in trio]
        lengths = [e - s + 1 for s, e in zip(starts, ends)]

        # 判据 3：三线**同起同长**（☰ 是齐整的三横）。这条最强 ——
        # 实测真 ☰ 三行是 17..31 一字不差；干扰项总是长度不一/起点漂移。
        if max(lengths) - min(lengths) > max(1, MENU_BARWH_RATIO * max(lengths)):
            continue
        if max(starts) - min(starts) > 1 or max(ends) - min(ends) > 1:
            continue

        # 判据 2：等距
        gaps = [centers[j + 1] - centers[j] for j in range(len(centers) - 1)]
        if min(gaps) <= 0:
            continue
        # 判据 2b：间距下限。真 ☰ 在最小窗口 1458x800 上间距也有 5.0；
        # 翻转帧的干扰项只有 3.0，属「过密的假三线」（见 MENU_MIN_GAP 注释）。
        if min(gaps) < MENU_MIN_GAP:
            continue
        mean_gap = sum(gaps) / len(gaps)
        dev = max(abs(g - mean_gap) for g in gaps) / mean_gap
        if dev > MENU_GAP_TOL:
            continue

        # 判据 2c：**左内边距带**。☰ 贴着窗口左内边距，四张真帧的右边缘占比
        # 恒在 0.021~0.026；翻转帧干扰项在 0.041，明显带外。这条是排除
        # 「左上角里的其它图标」的关键 —— 它们比 ☰ 更靠右。
        if max(ends) > w * MENU_X1_FRAC:
            continue

        cand = {
            "pos": (min(starts), max(0, int(centers[0]) - 2)),
            "bbox": (min(starts), int(centers[0]), max(ends), int(centers[-1])),
            "centers": [round(c, 1) for c in centers],
            "gaps": [round(g, 2) for g in gaps],
            "line_len": max(lengths),
            "score": max(0.0, 1.0 - dev / MENU_GAP_TOL),
        }
        # 评分下限：dev 再小也可能只是「勉强等距」，低分候选不可采信
        if cand["score"] < MENU_MIN_SCORE:
            continue
        if best is None or cand["score"] > best["score"]:
            best = cand

    if best is None and log:
        log(f"    ☰ 检测：{len(geom)} 条候选线中无「连续三条同起同长且等距」，否决")
    return best


def find_sidebar_item(frame_rgb, index, log=None):
    """程序化定位侧栏第 `index` 个菜单项（0-based）的文字行中心。

    为什么不用截图模板 / 绝对坐标：
      - 绝对 y 随窗口尺寸变（INV-39），实测 1458x800 下「任务」在 y≈184，
        而在 1875x1250 的旧帧上侧栏整体位置不同；
      - 侧栏项有 9 个，其中「任务」与「计划任务」**子串歧义**
        （「计划任务」含「任务」二字），模板匹配易歧义。
    改用**结构**：侧栏是一列**等行距**的「图标+文字」项。
    算法：
      1. 取侧栏横向窄带，按行统计亮像素，合并成文字行簇；
      2. 丢掉 ☰ 自身那三行（它们间距极小、总高很小）；
      3. 在剩余簇里找**最长的一段近似等距**序列 —— 那就是菜单列表；
      4. 取该序列的第 `index` 项。

    返回 {"pos": (x, y), "items": [...], "pitch": p, "index": index} 或 None。
    pos 是**该项图标所在处**的窗口内坐标（点击用）。
    """
    h, w = frame_rgb.shape[:2]
    y_end = min(h, int(h * SIDEBAR_SCAN_H_FRAC))
    x1 = min(w, SIDEBAR_TEXT_X1)
    if x1 <= SIDEBAR_TEXT_X0 or y_end < 16:
        return None

    g = to_gray(frame_rgb[:y_end, SIDEBAR_TEXT_X0:x1])
    bright = g > SIDEBAR_TEXT_THR

    rows = []
    for y in range(g.shape[0]):
        n = int(bright[y].sum())
        if n >= SIDEBAR_MIN_PIX:
            rows.append(y)
    if not rows:
        return None

    # 合并成簇
    groups, cur = [], [rows[0]]
    for y in rows[1:]:
        if y - cur[-1] <= SIDEBAR_GAP:
            cur.append(y)
        else:
            groups.append(cur)
            cur = [y]
    groups.append(cur)

    cl = []
    for gp in groups:
        y0, y1 = gp[0], gp[-1]
        if y1 - y0 > 40:            # 太高，多半是整块面板而非一项
            continue
        cl.append({"y0": y0, "y1": y1, "cy": (y0 + y1) / 2.0, "n": len(gp)})

    # 丢掉 ☰：它由三条极窄的线组成，总高很小且簇内行数少。
    # 实测 ☰ 在 y=58..69（总高 12），而菜单项文字高 ~16。
    cl = [c for c in cl if not (c["y1"] - c["y0"] <= 12 and c["cy"] < y_end * 0.20)]

    if len(cl) < SIDEBAR_MIN_ITEMS:
        if log:
            log(f"    [侧栏] 只找到 {len(cl)} 个候选簇，不足以判定菜单列表")
        return None

    # 在簇序列里找最长的一段「近似等距」子序列。
    # 逐一起点贪心扩展：只要下一个簇与当前行距偏差 <= SIDEBAR_PITCH_TOL 就纳入。
    best = None
    for i in range(len(cl)):
        seq = [cl[i]]
        pitches = []
        for j in range(i + 1, len(cl)):
            d = cl[j]["cy"] - seq[-1]["cy"]
            if d <= 0:
                continue
            if pitches:
                ref = sum(pitches) / len(pitches)
                if ref <= 0 or abs(d - ref) / ref > SIDEBAR_PITCH_TOL:
                    break
            pitches.append(d)
            seq.append(cl[j])
        if best is None or len(seq) > len(best[0]):
            best = (seq, pitches)

    seq, pitches = best
    if len(seq) < SIDEBAR_MIN_ITEMS or not pitches:
        if log:
            log(f"    [侧栏] 未找到等距项序列（最长 {len(seq)} 项）")
        return None

    pitch = sum(pitches) / len(pitches)
    if log:
        log(f"    [侧栏] 等距列表 {len(seq)} 项，行距 {pitch:.1f}px，"
            f"首项 y={seq[0]['cy']:.0f}")

    if index >= len(seq):
        if log:
            log(f"    [侧栏] 只识别出 {len(seq)} 项，取不到序号 {index}")
        return None

    item = seq[index]
    # 点击落在该项上。图标与文字同属一行，取该行中心 y；
    # x 取侧栏图标列（实测图标中心 x≈30，与 ☰ 同列）。
    cx = 30 if w >= 300 else max(4, w // 2)
    return {
        "pos": (cx, int(item["cy"])),
        "items": [int(c["cy"]) for c in seq],
        "pitch": round(pitch, 2),
        "index": index,
        "n_items": len(seq),
    }


def verify_identity(frame_rgb, sidebar_tpl=None, log=None):
    """身份校验（INV-12 / INV-18 / INV-23 的第一道）。

    确认这一帧**确实来自 ok-ww**。内容非全黑是必要条件，不是充分条件 ——
    抓到别的窗口时画面同样「健康」（实测：驱动终端与 ok-ww 同为 1458x800，
    INV-1 尺寸校验与 INV-13 非全黑校验**双双通过**，只有本函数拦住了它）。

    主路径：**程序化 ☰ 检测**（find_menu_glyph），页面无关、不依赖截图资产。
    回退：  sidebar_tpl 给定时，用旧的模板匹配口径（1_ww.png + (16,215)）。
            该回退仅在主路径失败时启用，用于兼容资产采集期的旧帧。

    sidebar_tpl 可省略 —— 主路径不需要它。签名保持兼容，故 5 个调用点无需改动。
    """
    glyph = find_menu_glyph(frame_rgb, log=log)
    if glyph is not None:
        # 位置合理性：☰ 必须落在**左上角**。
        #
        # ⚠️ 这里**绝不可以用某个尺寸下的绝对观测值**做判据。
        # 曾经的教训（本文件两处同型错误）：
        #   - 旧口径把 (16,215)（取自 1822x1000）当全局常量 ⇒ 1458x800 下失配；
        #   - 本次修复中我一度把 MENU_ANCHOR_Y=56（取自 1458x800）当全局常量，
        #     结果 1875x1250 下 ☰ 实际在 y=71，|71-56|=15 > 14，
        #     **把正确的检测结果丢掉、反而回退到坏模板**，且自检显示「通过」。
        # 正确做法：只约束「在左上角」这一**结构性**事实，用窗口尺寸的相对比例。
        h, w = frame_rgb.shape[:2]
        px, py = glyph["pos"]
        if px > w * MENU_CORNER_W_FRAC or py > h * MENU_CORNER_H_FRAC:
            if log:
                log(f"    ☰ 检测：位置 {glyph['pos']} 不在左上角"
                    f"（限 x<={w*MENU_CORNER_W_FRAC:.0f}, y<={h*MENU_CORNER_H_FRAC:.0f}），按失配处理")
        else:
            return {
                "score": glyph["score"],
                "pos": glyph["pos"],
                "method": "menu-glyph",
                "bbox": glyph["bbox"],
                "centers": glyph["centers"],
                "gaps": glyph["gaps"],
            }

    # --- 回退：旧模板口径 -------------------------------------------------
    if sidebar_tpl is None:
        raise GuardFailure(
            "INV-12",
            "身份校验失败：左上角未检出 ☰（三条等距水平亮线），"
            "且未提供回退模板 —— 这一帧很可能不是 ok-ww")

    if log:
        log("    ☰ 程序化检测未通过，回退到模板口径（1_ww.png）")

    res = match_best(frame_rgb, sidebar_tpl)
    if res is None:
        raise GuardFailure("INV-12", "侧栏图标模板比帧还大，无法匹配")
    score, mx, my = res
    if score < IDENTITY_MIN:
        raise GuardFailure(
            "INV-12",
            f"身份校验失败：☰ 未检出，且侧栏图标 score={score:.4f} < {IDENTITY_MIN}")
    if abs(mx - SIDEBAR_X) > SIDEBAR_TOL or abs(my - SIDEBAR_Y) > SIDEBAR_TOL:
        raise GuardFailure(
            "INV-12",
            f"身份校验失败：侧栏图标位置 ({mx},{my}) 偏离预期 "
            f"({SIDEBAR_X},{SIDEBAR_Y})±{SIDEBAR_TOL}")

    return {"score": score, "pos": (mx, my), "method": "template-fallback"}


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
