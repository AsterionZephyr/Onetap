"""ok-nte 专项模块 —— 定位、判据、节点 8 的 ok-nte 实现。

**归属规则（docs/adr/0003）**：改 ok-nte 的行为只改本文件；共用层只按需惰性
import 本模块（PEP 562 垫片见 match.py / verdict.py / step8 末尾）。

内容来源（2026-10-19 搬迁，逐行切片，无改写）：
  - 定位：orchestrator/match.py 的 ok-nte 段（NTE_* 几何常量、nte_cyan_mask、_runs、
    nte_find_sidebar_highlight、nte_find_checkboxes、nte_find_start_button、nte_locate_start）
  - 判据：orchestrator/verdict.py 的 NTE_* 标记、parse_nte_summary、nte_failures、
    nte_verdict、执行器暂停检测（FAULT #30）
  - 节点 8：orchestrator/steps/step8_run_task.py 的 NTE_* 等待常量、nte_wait_game_settled /
    nte_navigate_to_daily / nte_locate_start_button / wait_for_nte_completion
"""
import re
import time
from pathlib import Path

import numpy as np

from .. import capture as capture_mod
from .. import input as input_mod
from .. import match as match_mod
from .. import programs as programs_mod
from .. import state as state_mod
from .. import watchdog as watchdog_mod
from .. import win32
from .. import window
from ..errors import GuardFailure
from ..frameops import finish, frame_changed, grab, shot  # noqa: F401
from ..orchestrator import (CLICK_RETRIES, NAV_RETRIES, POLL_INTERVAL,  # noqa: F401
                            TOTAL_TIMEOUT)
from ..statuses import (COMPLETED, FAILED, NO_TASK, RUNNING, STALLED,  # noqa: F401
                        TERMINAL_MARK_EXIT_GAME,
                        SUCCESS, TIMEOUT, UNKNOWN)

# 同 apps/ww.py：被搬来的函数体按原文件的裸名字引用共用内核
ensure_foreground = input_mod.ensure_foreground
guarded_click = input_mod.guarded_click
grab_frame = capture_mod.grab_frame
client_to_screen = win32.client_to_screen
game_processes = watchdog_mod.game_processes
NTE = programs_mod.NTE


def _default_log_window():
    """默认日志窗口（惰性 import：verdict.LogWindow 与本模块互相可见但不同期加载）。"""
    from ..verdict import LogWindow

    return LogWindow()



# ==========================================================================
# 一、定位（原 orchestrator/match.py 的 ok-nte 段）
# ==========================================================================

# ==========================================================================
# ok-nte（v1.4.14）—— 任务页结构与 ok-ww **不同构**，见 FAULT #22
# ==========================================================================
#
# ⚠️ 文档（FRAMEWORK §0.1.2 / HANDOFF）曾断言 ok-nte「v1.4.8 起与 ok-ww 同构：
# 逐任务行、每行一个开始按钮、9 个同款按钮」。**v1.4.14 实测推翻了这个前提**：
#
#     每行 = 「复选框 + 任务名 + 展开箭头」，**没有逐行按钮**；
#     全页只有 **1 个「开始」**，在右下角。
#
# 也就是说 ok-nte 又回到了文档所说的「已被淘汰」的旧模型。
# ⇒ **ok-ww 的行扫描定位（locate_daily_row / scan_row_button）不适用于 ok-nte。**
# 下面是一套按 ok-nte 真实结构写的独立定位器。

# --- ok-nte 几何常量（1500x1000 实测；**只用结构性比例，不用绝对像素**）------
NTE_CHECK_X0, NTE_CHECK_X1 = 150, 260   # 复选框所在 x 带（窗口内坐标）
NTE_CHECK_SIZE = 20                      # 复选框边长（实测恒 20x20）
NTE_ROW_PITCH = 62                       # 行距（实测恒 62.0px @1500x1000）
NTE_BOTTOM_FRAC = 0.90                   # 底部栏起始（y > h*0.90 视为底部栏）
NTE_START_MIN_W = 50                     # 「开始」按钮最小宽度（实测 78）
NTE_CHECK_MIN_PIX = 8                    # 判为复选框的最少青色像素
# 侧栏「当前选中」青色竖条所在 x 带（实测 x≈2..5）
NTE_HL_X0, NTE_HL_X1 = 0, 12
# ok-nte 侧栏「日常任务」的**内容簇序号**（0-based）。
# ⚠️ 实测 1500x1000 下侧栏是 11 项等距列表（40.0px），日常任务为第 4 项。
#    文档 FRAMEWORK §0.1.2 记的是 index 3 —— 那是旧版布局，**已过期**。
#    实测交叉验证：青色选中竖条落在 y=263.5，与 idx=4 的 y=263 **一致**。
NTE_SIDEBAR_ITEM_DAILY = 4
# ⚠️ 尺寸闸门：实测真复选框恒 20x20。若不给上限，**整帧纯青**也会被当做一个
# 横贯全宽的巨块，从而骗过 nte_locate_start（探针实测复现）。上限给得宽松
# （2x），以容忍不同 DPI，但仍足以拒绝全屏色块。
NTE_CHECK_MAX_W = NTE_CHECK_SIZE * 2 + 4
NTE_CHECK_MAX_H = NTE_CHECK_SIZE * 2 + 4

# 勾选态颜色（FRAMEWORK §0.1.2）：青 —— B/G>150 且 R<130
NTE_CYAN_R_MAX = 130
NTE_CYAN_GB_MIN = 150


def nte_cyan_mask(frame_rgb):
    """ok-nte 的「青色」掩码（勾选态复选框 / 开始按钮 都是这个色）。

    ⚠️ ok-ww 的按钮高亮色是**白**（亮度>200），ok-nte 是**青**。
    两个程序**不可共用一个色判据**（FRAMEWORK §0.1.2）。
    """
    f = frame_rgb.astype("int16")
    r, g, b = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    return (g > NTE_CYAN_GB_MIN) & (b > NTE_CYAN_GB_MIN) & (r < NTE_CYAN_R_MAX)


def _runs(mask_1d, offset=0, minlen=1):
    out, y, n = [], 0, len(mask_1d)
    while y < n:
        if mask_1d[y]:
            y0 = y
            while y < n and mask_1d[y]:
                y += 1
            if y - y0 >= minlen:
                out.append((y0 + offset, y - 1 + offset))
        else:
            y += 1
    return out


def nte_find_sidebar_highlight(frame_rgb, log=None):
    """定位 ok-nte 侧栏**当前选中项**（青色竖条 + 青字）。

    这是比「数序号」更稳的页面判据：ok-nte 侧栏有**两组**菜单
    （上组＝页面导航、下组＝任务菜单），两组里都出现「任务」字样，
    按名字子串定位必然歧义（AGENTS.md 明令禁止子串匹配）。

    实测选中态特征：**左边缘一条青色竖条**（x≈2..5，高约 26px），
    文字同时变青。本函数取竖条位置。

    返回 {"cy": 中心y, "y0","y1","x0","x1"} 或 None（无选中项）。
    """
    h, w = frame_rgb.shape[:2]
    cyan = nte_cyan_mask(frame_rgb)
    # 只扫最左侧窄带（竖条所在处），避开内容区里的青色元素
    xs = min(w, NTE_HL_X1)
    if NTE_HL_X0 >= xs:
        return None
    band = cyan[:, NTE_HL_X0:xs]
    spark = band.sum(axis=1) >= 2
    bars = []
    for a, b in _runs(spark, minlen=8):
        sub = band[a:b + 1]
        cols = np.where(sub.sum(axis=0) > 0)[0]
        bars.append({
            "cy": (a + b) / 2.0, "y0": a, "y1": b,
            "x0": int(cols.min()) + NTE_HL_X0,
            "x1": int(cols.max()) + NTE_HL_X0,
        })
    if log:
        log(f"    [ok-nte] 侧栏选中竖条 {len(bars)} 条："
            f"{[round(b['cy'], 1) for b in bars]}")
    if not bars:
        return None
    # 取最长的（真竖条比图标碎片长）
    bars.sort(key=lambda b: -(b["y1"] - b["y0"]))
    return bars[0]


def nte_find_checkboxes(frame_rgb, log=None):
    """列出 ok-nte 任务页所有**已勾选**的复选框（青色 20x20）。

    返回 [{"cy": 中心y, "y0","y1","x0","x1","checked": True}, ...]，按 y 升序。

    ⚠️ 三处陷阱（均已实测）：
      1. **未勾选的复选框是灰色**，不满足青色判据 ⇒ 本函数只返回**已勾选**的。
         要区分「未勾选」与「该行不存在」，需另配灰色检测或按行距外推。
      2. **底部「取消全选」复选框同色同尺寸**（实测 y=954..973 @1500x1000），
         必须按 `y > h*NTE_BOTTOM_FRAC` 排除，否则会被当成第 9 个任务行。
      3. 行距**在任务列表内恒为 62**，但**首行与第二行之间可能因折叠而变**
         （实测曾见 124 = 2x62，即中间一行未勾选）。

    ⚠️ 尺寸闸门不是多余的：探针实测**整帧纯青**时本函数会「检出」一个横贯
    全宽的巨块，从而骗过 nte_locate_start。加宽/高上限后该合成帧被正确拒绝。
    """
    h, w = frame_rgb.shape[:2]
    cyan = nte_cyan_mask(frame_rgb)
    x1 = min(w, NTE_CHECK_X1)
    if NTE_CHECK_X0 >= x1:
        return []
    band = cyan[:, NTE_CHECK_X0:x1]
    spark = band.sum(axis=1) >= NTE_CHECK_MIN_PIX
    y_cut = int(h * NTE_BOTTOM_FRAC)
    boxes = []
    for a, b in _runs(spark, minlen=NTE_CHECK_SIZE - 4):
        if a >= y_cut:
            continue                      # 陷阱 2：底部栏
        if b - a + 1 > NTE_CHECK_MAX_H:   # 尺寸闸门：见 docstring 警告
            continue
        sub = band[a:b + 1]
        cols = np.where(sub.sum(axis=0) > 0)[0]
        if not len(cols):
            continue
        bw = int(cols.max() - cols.min() + 1)
        if bw > NTE_CHECK_MAX_W:          # 尺寸闸门
            continue
        boxes.append({
            "cy": (a + b) / 2.0,
            "y0": a, "y1": b,
            "x0": int(cols.min()) + NTE_CHECK_X0,
            "x1": int(cols.max()) + NTE_CHECK_X0,
            "checked": True,
        })
    if log:
        gaps = [round(boxes[i + 1]["cy"] - boxes[i]["cy"], 1)
                for i in range(len(boxes) - 1)]
        log(f"    [ok-nte] 已勾选复选框 {len(boxes)} 个，行距={gaps}")
    return boxes


def nte_find_start_button(frame_rgb, log=None):
    """定位 ok-nte **右下角唯一的「开始」按钮**（青色实心块）。

    与 ok-ww 的 `scan_row_button`（按行扫描最右亮像素）**完全不同**：
    ok-nte 全页只有一个「开始」，位置固定在右下角。

    返回 {"box": (x0,y0,x1,y1), "center": (cx,cy), "size": (w,h)} 或 None。
    """
    h, w = frame_rgb.shape[:2]
    cyan = nte_cyan_mask(frame_rgb)
    y_cut = int(h * NTE_BOTTOM_FRAC)
    bot = cyan[y_cut:, :]
    if not bot.size:
        return None

    # 找宽度足够的列簇（排除图标一类细窄元素）
    cspark = bot.sum(axis=0) >= 4
    cands = []
    for a, b in _runs(cspark, minlen=NTE_START_MIN_W):
        if b - a + 1 < NTE_START_MIN_W:
            continue
        sub = bot[:, a:b + 1]
        rows = np.where(sub.sum(axis=1) > 0)[0]
        if not len(rows):
            continue
        cands.append({
            "box": (a, int(rows.min()) + y_cut, b, int(rows.max()) + y_cut),
            "center": ((a + b) // 2, int((rows.min() + rows.max()) // 2) + y_cut),
            "size": (b - a + 1, int(rows.max() - rows.min() + 1)),
        })
    if not cands:
        if log:
            log("    [ok-nte] 底部未找到「开始」按钮（青色块）")
        return None

    # 取**最右**的那个：ok-nte 的「开始」在右下角，底部左侧是「取消全选」等
    cands.sort(key=lambda c: -c["center"][0])
    best = cands[0]
    if log:
        bx0, by0, bx1, by1 = best["box"]
        log(f"    [ok-nte] 「开始」按钮 窗口内 x={bx0}..{bx1} y={by0}..{by1} "
            f"中心={best['center']}")
    return best


def nte_locate_start(frame_rgb, log=None):
    """ok-nte 定位总入口：确认在任务页 + 返回「开始」按钮坐标。

    判据（两者都要成立，否则报 INV-24）：
      1. 至少检出 1 个已勾选复选框（任务列表存在）；
      2. 右下角存在「开始」按钮。

    ⇒ 用**两个独立特征**交叉验证，而不是单靠一个锚点：
    这正是 ADR 0002 的「联合唯一性」思想在 ok-nte 上的对应实现。
    """
    boxes = nte_find_checkboxes(frame_rgb, log=log)
    if not boxes:
        raise GuardFailure(
            "INV-24",
            "ok-nte 任务页判定失败：未检出任何**已勾选**的复选框。\n"
            "  => 可能原因：不在任务页、任务列表为空、所有任务都未勾选、"
            "或界面改版（复选框不再是青色 20x20）。")

    btn = nte_find_start_button(frame_rgb, log=log)
    if btn is None:
        raise GuardFailure(
            "INV-24",
            f"ok-nte 任务页判定失败：检出 {len(boxes)} 个复选框，"
            "但右下角未找到「开始」按钮。\n"
            "  => 可能原因：底部栏被遮挡、窗口过矮、或界面改版。")

    # 交叉验证：复选框行距应该接近 NTE_ROW_PITCH 的整数倍（结构性校验）
    if len(boxes) >= 2:
        gaps = [boxes[i + 1]["cy"] - boxes[i]["cy"] for i in range(len(boxes) - 1)]
        base = min(gaps)
        bad = [g for g in gaps if base > 0 and abs(g / base - round(g / base)) > 0.15]
        if bad and log:
            log(f"    [ok-nte][警告] 行距不成整数倍：{gaps} —— 可能有行未被勾选")

    return {"boxes": boxes, "button": btn, "n_checked": len(boxes)}



# ==========================================================================
# 二、判据（原 orchestrator/verdict.py 的 ok-nte 段）
# ==========================================================================

# --- ok-nte 关键标记（实测自真日志）----------------------------------------

# ★ 终止标记：进程收尾，**最强的完成证据**
NTE_TERMINAL_MARK = TERMINAL_MARK_EXIT_GAME

# 日常任务结束
NTE_DAILY_END = r"DailyRoutineTask:结束执行日常任务"

# 逐项结果
NTE_ITEM_DONE = r"DailyRoutineTask:任务完成:\s*(.+)"
NTE_ITEM_FAIL = r"DailyRoutineTask:任务失败:\s*(.+)"

# 关闭游戏（HTGame.exe —— 与 ok-ww 的 Client-Win64-Shipping.exe 不同）
NTE_KILL_GAME = r"Trying to kill the exe \{[^}]*HTGame\.exe"

# 日志目录
NTE_LOGDIR = Path(
    r"E:\TOOLS\ScriptsGames\ok-nte\data\apps\ok-nte\working\logs")

# --- 汇总行的两种格式（FAULT #18）------------------------------------------
#
# **新格式**（ok-nte v1.4.8 起）——三行独立，带 `info_set` 前缀，关键字后**无冒号**：
#     DailyRoutineTask:info_set success ['异象界域', ...]
#     DailyRoutineTask:info_set failed []
#     DailyRoutineTask:info_set skipped ['异象追猎']
NTE_SUMMARY_NEW = (
    r"DailyRoutineTask:info_set success\s*(\[[^\]]*\])"
    r"\s*\n.*?DailyRoutineTask:info_set failed\s*(\[[^\]]*\])"
    r"\s*\n.*?DailyRoutineTask:info_set skipped\s*(\[[^\]]*\])")
#
# **老格式**（≤ v1.4.7）——同一行三段，关键字后**有冒号**：
#     DailyRoutineTask:success: ['甲', '乙']\nfailed: []\nskipped: []
NTE_SUMMARY_OLD = (
    r"DailyRoutineTask:success:\s*(\[[^\]]*\])"
    r"\s*failed:\s*(\[[^\]]*\])"
    r"\s*skipped:\s*(\[[^\]]*\])")


def _as_list(s):
    """把 `['甲', '乙']` 这样的字面量解析成列表。

    ⚠️ 不是 JSON —— 实测日志里用的是**单引号**，故 `json.loads` 会失败。
    这里做的是**逐项剥离引号**，与 probe 侧 `_list` 行为一致。
    """
    return [x.strip().strip("'\"") for x in s.strip("[]").split(",") if x.strip()]


def parse_nte_summary(text):
    """取 ok-nte 汇总行的 (success, failed, skipped) 三个列表。

    **先试新格式、再退老格式**；都不中 ⇒ `(None, None, None)`。

    ⚠️ **要么三段都给，要么三段都给 None**。老实现在失配时返回
    `(None, <失败项>, None)`，其中 `failed` 看似是正确的空列表，
    实则只是「恰好没失败」—— 真失败时同样表现为「没有失败」，无从察觉。
    调用方拿到全 None 时**必须警示**，不得当成「没有失败」。
    """
    for pat in (NTE_SUMMARY_NEW, NTE_SUMMARY_OLD):
        m = re.search(pat, text, re.S)
        if m:
            return _as_list(m.group(1)), _as_list(m.group(2)), _as_list(m.group(3))
    return None, None, None


def nte_failures(text):
    """取出失败项原文（**不参与判定**，仅用于完成后打印）。"""
    succ, fail, skip = parse_nte_summary(text)
    out = list(fail) if fail else []
    out.extend(x.strip() for x in re.findall(NTE_ITEM_FAIL, text))
    seen, uniq = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def nte_verdict(text, still_running=False):
    """对 ok-nte 的日志文本判定终态。返回 (verdict, evidence[])。

    判定只看**是否完成**：

        SUCCESS  : 出现终止标记，**或**出现「结束执行日常任务」
        RUNNING  : 无终止标记且进程仍在运行
        NO_TASK  : 无任何任务痕迹
        UNKNOWN  : 其他（**证据不足绝不报成功**，INV-30）
    """
    if not text or not text.strip():
        # ⚠️ 顺序很重要（FAULT #25 的同族问题）：进程还在跑时，日志暂时为空是
        # **正常**的（刚点击、ok-nte 还没写第一批日志），属于 RUNNING 而非 UNKNOWN。
        # 早期实现无条件返回 UNKNOWN，会让操作者看到「unknown」而误以为出了事。
        if still_running:
            return RUNNING, ["本次运行尚无新增日志，但进程在运行"]
        return UNKNOWN, ["日志为空（本次运行尚无新增内容）"]

    ev = []
    terminal = bool(re.search(NTE_TERMINAL_MARK, text))
    daily_end = bool(re.search(NTE_DAILY_END, text))
    killed = bool(re.search(NTE_KILL_GAME, text, re.I))

    done_items = re.findall(NTE_ITEM_DONE, text)
    fail_items = re.findall(NTE_ITEM_FAIL, text)

    succ, fail, skip = parse_nte_summary(text)
    if succ is not None or fail is not None or skip is not None:
        ev.append(f"汇总 success={succ} failed={fail} skipped={skip}")
    else:
        # FAULT #18：必须说出来。两种可能 ——
        #   (a) 日志里确实没有汇总行（早退 / 崩溃）；
        #   (b) **程序升级又改了格式**（老正则就是这样死的）。
        # 无论哪种，都**不能**静默当成「没有失败」。
        ev.append(f"[!] 未解析到汇总行（格式可能又变了）："
                  f"逐项 完成 {len(done_items)} 项 {done_items[-6:]}, "
                  f"失败 {len(fail_items)} 项 {fail_items[-4:]}")

    ev.append(f"终止标记={terminal} 日常结束={daily_end} 杀游戏={killed}")

    if not (done_items or fail_items or terminal or daily_end):
        if still_running:
            return RUNNING, ev + ["尚无任务痕迹，进程在运行"]
        return NO_TASK, ev + ["无任务痕迹"]

    if terminal:
        return SUCCESS, ev + ["出现终止标记（进程收尾）"]
    if daily_end:
        return SUCCESS, ev + ["日常任务结束"]

    if still_running:
        return RUNNING, ev + ["仍在运行"]

    return UNKNOWN, ev + ["序列不完整且无终止标记"]




# --- FAULT #30：执行器暂停（游戏窗口被最小化）-----------------------------
#
# ok-nte 在游戏窗口被最小化时写下这一行，然后**暂停自己的执行器**：
#
#     ERROR update_window_size hwnd_window:og.executor.pause \
#           pos_invalid: (-32000, -32000, 0, 0)
#
# `-32000` 正是 win32.ICONIC_SENTINEL（最小化哨兵）。暂停后进程**还在**、
# 终止标记**永远不来** ⇒ 只看「终止标记/进程存活」的等待循环必然空转到
# --total-timeout 才报 TIMEOUT，**白烧半小时且归因错误**（报「超时」而非「卡住」）。
#
# ⚠️ **不能一见到 pos_invalid 就断定卡死**。实测 ok-script.2026-10-12.log：
# 20:07:19 出现哨兵 pause，但 20:07:40 又跑了 FishingTask、20:11:22 正常
# `ok:quit app` 退出 —— 它是**活过来的**（那次窗口被人手动最小化过）。
# 所以判定要同时满足：哨兵 pause 出现过、且之后**既无业务行也无收尾动作**。
NTE_EXECUTOR_PAUSE = r"og\.executor\.pause\s+pos_invalid:\s*\(\s*-32000\s*,\s*-32000"

# 业务行：任务执行器真正在做事的证据。
# ⚠️ 必须覆盖**所有**任务类，不能只写 Daily* —— 实测 10-12 那次跑的是
# FishingTask（钓鱼），只用 Daily 会把它误判成「没干活」。
_NTE_BIZ_RE = re.compile(r"TaskExecutor\s+\w+Task[:：]"
                         r"|开始任务|任务完成|found Labels|info_set (轮次|当前阶段)")
_NTE_NOISE_RE = re.compile(r"update_window_size|hwnd_window|connected:"
                           r"|do_update_window_size")
# 收尾动作：出现即说明进程在正常收场，不是卡死
_NTE_EXIT_RE = re.compile(r"ok:quit app|Executor destroy|Attempting to terminate process"
                          r"|handler stopping")


def nte_executor_paused(text):
    """判断 ok-nte 是否**停在那里不动了**（执行器暂停且无进展）。

    返回 (paused, evidence)。`paused` 为 True 表示：出现过最小化哨兵导致的
    `og.executor.pause`，且**之后再没有任何业务行、也没有任何收尾动作**。

    这是 FAULT #30 的判据；详见上方注释里 10-12 那条反证。
    """
    pauses = list(re.finditer(NTE_EXECUTOR_PAUSE, text))
    if not pauses:
        return False, ""

    tail = text[pauses[-1].end():]
    biz = 0
    exit_actions = 0
    for line in tail.splitlines():
        if not line.strip():
            continue
        if _NTE_BIZ_RE.search(line) and not _NTE_NOISE_RE.search(line):
            biz += 1
        if _NTE_EXIT_RE.search(line):
            exit_actions += 1

    paused = (biz == 0 and exit_actions == 0)
    if paused:
        return True, (f"检出执行器暂停（pos_invalid 最小化哨兵）{len(pauses)} 次，"
                      f"之后无业务日志、无收尾动作 —— 游戏窗口很可能被最小化，"
                      f"ok-nte 停住了（FAULT #30）")
    return False, (f"检出执行器暂停 {len(pauses)} 次，但之后仍有业务行 {biz} / "
                   f"收尾 {exit_actions} —— 已自行恢复，不算卡死")




# ==========================================================================
# 三、节点 8（原 orchestrator/steps/step8_run_task.py 的 ok-nte 段）
# ==========================================================================

# ok-nte 见到终止标记后的**收尾宽限**（FAULT #27）。
# 终止标记是「将要退出」的宣告；实测它还要 5.0s 才开始杀游戏、10.1s 才写完
# `ok:quit app`。立刻返回会让节点 9 抢在它关游戏之前把它杀掉，
# 留下全屏孤儿游戏窗口。这段窗口内等它自己退出（等不到就交给节点 9）。
NTE_SETTLE_SECONDS = 20.0

# --- FAULT #28：ok-nte 一启动就自动拉游戏，游戏全屏会把抓帧打成全黑 --------
#
# 实测（ok-script.log 每次启动都有这一对，间隔 ~4 秒）：
#
#     MainWindow:MainWindow showEvent Kill Launcher After Start
#     LauncherTask:Starting launcher from configured path: ...NTEGame.exe
#
# 即 **ok-nte 窗口一出现就自己去拉游戏**，与「点开始」无关。
# 游戏起来时是全屏 DirectX，屏幕抓图返回**纯黑** ⇒ INV-13 拦住 ⇒ 节点 8 只有 2.4s
# 就 FAILED（实测 run-20261016-031137）。
#
# 成功与失败只差**时序**：
#   - run-20261016-024410（成功）：节点 8 起跑 02:44:10；游戏 02:45:29 就位；
#     点击在 02:46+ ⇒ 点的时候游戏早已稳定，画面可读。
#   - run-20261016-031137（失败）：节点 8 起跑 03:11:37；03:12:35 ok-nte 拉游戏；
#     节点 8 恰在 **03:12:35** 开始干活 ⇒ 抓帧撞上游戏全屏 ⇒ 全黑。
#
# 故节点 8 在 ok-nte 上开工前，必须先等「游戏拉起并稳定」这件事过去：
#   1. 若游戏**尚未出现**：等它出现（ok-nte 一定会拉）；
#   2. 出现后：再等画面**连续可读**（不是全黑）若干次，才算稳定。
# 只看「进程在不在」不够 —— 进程刚出现时窗口还没全屏，抓到的可能仍是
# ok-nte；而下一瞬就变全黑了。所以判据落在**抓帧是否可读**上。
NTE_GAME_WAIT_SECONDS = 120.0   # 等游戏进程出现的上限（实测 03:12:35→03:12:58 约 23s）
NTE_READABLE_SAMPLES = 3        # 需连续这么多次「可读」才算稳定
NTE_SETTLE_POLL = 2.0           # 稳定检测的轮询间隔

# FAULT #30：检测到「执行器暂停且零进展」后，再给它这么久自行恢复。
# 实测恢复游戏窗口**有时**能让它继续（13s 后写 hwnd changed,connected:1），
# **有时不能**（恢复后再度沉默）。所以先给宽限期，仍无进展才判定 STALLED。
# 取 90s：足够容忍一次恢复尝试，又远小于 1800s 的兜底上限。
NTE_STALL_GRACE_SECONDS = 90.0





def nte_wait_game_settled(state, log):
    """等 ok-nte 自动把游戏拉起来、且画面重新可读（FAULT #28）。

    为什么需要：**ok-nte 窗口一出现就自己去拉游戏**（实测每次启动都有
    `showEvent Kill Launcher After Start` → `Starting launcher from ...`，
    间隔约 4 秒，与「点开始」无关）。游戏是全屏 DirectX，起来时屏幕抓图
    返回纯黑 ⇒ 撞上这段就会 INV-13 失败。

    实测成功与失败的唯一差别就是**节点 8 开工时游戏处于哪个阶段**：
    游戏已稳定 ⇒ 一路通；正在起 ⇒ 抓帧全黑、节点 8 只活 2.4s。

    判据落在「**抓帧是否可读**」而不是「进程在不在」：
    进程刚出现时窗口还没全屏，此刻抓到的可能仍是 ok-nte，下一瞬才变黑。
    故必须连续若干次抓到非全黑帧才算稳定。

    返回 True 表示已稳定；False 表示等待超时（**不抛异常** —— 此时画面可能
    只是暂时不可读，继续往下走让既有的 INV-13 闸门去裁决，比在这里直接
    失败更符合「证据不足不臆断」）。
    """
    if not watchdog_mod.game_processes(programs_mod.NTE):
        log(f"  ok-nte 会自动拉起游戏；等它出现（上限 {NTE_GAME_WAIT_SECONDS:.0f}s）")
        t0 = time.time()
        while time.time() - t0 < NTE_GAME_WAIT_SECONDS:
            if watchdog_mod.game_processes(programs_mod.NTE):
                log(f"  [OK] 游戏进程已出现（等了 {time.time() - t0:.0f}s）")
                break
            time.sleep(NTE_SETTLE_POLL)
        else:
            log(f"  [警告] 等了 {NTE_GAME_WAIT_SECONDS:.0f}s 仍未见游戏进程；"
                "继续往下走（画面判据会自行裁决）")
            return False
    else:
        log("  游戏进程已在运行")

    # 连续 NTE_READABLE_SAMPLES 次抓到可读帧，才算画面稳定下来
    hwnd = state.get("hwnd")
    if not hwnd:
        return False
    good = 0
    fg_fail = 0
    t0 = time.time()
    while time.time() - t0 < NTE_GAME_WAIT_SECONDS:
        # ⚠️ 必须把「置前台失败」与「帧不可读」分开报（FAULT #29）。
        # 原先二者共用一个 `except GuardFailure`，于是置前台连续失败时
        # 被打成「画面仍未稳定」——**归因错误**，会把人引去查游戏遮挡，
        # 而真凶是前台锁。两者都会让抓帧失败，但修法完全不同。
        try:
            input_mod.ensure_foreground(hwnd, log=None)
        except GuardFailure as e:
            fg_fail += 1
            good = 0
            time.sleep(NTE_SETTLE_POLL)
            continue

        try:
            fr = capture_mod.grab_frame(hwnd)
            good += 1
            if good >= NTE_READABLE_SAMPLES:
                log(f"  [OK] 画面已稳定（连续 {good} 次可读，"
                    f"均值 RGB {fr.stats.get('mean_rgb') if fr.stats else '?'}）")
                return True
        except GuardFailure:
            good = 0
        time.sleep(NTE_SETTLE_POLL)

    if fg_fail and good == 0:
        log(f"  [警告] 等了 {NTE_GAME_WAIT_SECONDS:.0f}s 仍拿不到前台"
            f"（置前台失败 {fg_fail} 次）—— 这不是画面问题，"
            f"是**前台锁**被别的窗口占着（INV-8/FAULT #29）。"
            f"请关掉占前台的窗口（常见：DSH 自己的窗口、浏览器）")
    else:
        log(f"  [警告] 等了 {NTE_GAME_WAIT_SECONDS:.0f}s 画面仍未稳定"
            f"（连续可读仅 {good}/{NTE_READABLE_SAMPLES} 次）")
    return False


def nte_navigate_to_daily(state, frame, args, log):
    """ok-nte 导航：确认/进入「日常任务」页。返回 (frame, navigated)。

    ⚠️ 与 ok-ww 的差别（FAULT #22）：

      1. **目标页是「日常任务」，不是「任务」**。ok-nte 侧栏里有**两组**菜单，
         两组都含「任务」字样（上组 ▤「任务」＋下组「任务」/「日常任务」），
         按名字子串定位必然歧义 ⇒ **只能按序号**。
      2. 实测侧栏为 11 项等距列表（40.0px），**「日常任务」是第 4 项**。
         该序号**不是**文档里写的 3（文档基于旧版布局）。
      3. 页面判据不靠序号自证：点击后用 `nte_locate_start` **重新抓帧闭环验证**
         （复选框 + 右下角开始按钮两个独立特征），序号只用来找点击位置。
    """
    log("\n[8a] 导航：确认当前在「日常任务」页（ok-nte）")

    for attempt in range(1, NAV_RETRIES + 1):
        try:
            nte_locate_start(frame.rgb, log=(log if attempt == 1 else None))
            if attempt > 1:
                log(f"  [OK] 第 {attempt} 次抓帧确认：已在日常任务页")
            else:
                log("  [OK] 已在日常任务页（复选框 + 开始按钮双特征成立）")
            return frame, attempt > 1
        except GuardFailure as e:
            log(f"  第 {attempt} 次判定：当前不是日常任务页 —— "
                f"{e.detail.splitlines()[0]}")

        if attempt >= NAV_RETRIES:
            break

        if args.offline or args.dry_run:
            log("  [离线/DRY RUN] 不点击导航；直接进入定位环节以检验判据")
            return frame, False

        item = match_mod.find_sidebar_item(frame.rgb, NTE_SIDEBAR_ITEM_DAILY,
                                       log=log)
        if item is None:
            raise GuardFailure(
                "INV-24",
                f"无法程序化定位 ok-nte 侧栏第 "
                f"{NTE_SIDEBAR_ITEM_DAILY} 项（日常任务）。\n"
                "  => 可能原因：侧栏未展开、界面改版、窗口过矮。")

        hwnd = state.get("hwnd")
        if not hwnd:
            raise GuardFailure("INV-23", "导航需要窗口句柄（离线模式请加 --only-locate）")
        cx, cy = item["pos"]
        sp = win32.client_to_screen(hwnd, cx, cy)
        if sp is None:
            raise GuardFailure("INV-23", "ClientToScreen 失败")
        log(f"  侧栏第 {NTE_SIDEBAR_ITEM_DAILY} 项"
            f"（共 {item['n_items']} 项，行距 {item['pitch']}px）"
            f"窗口内点=({cx},{cy}) -> 屏幕 ({sp[0]},{sp[1]})")
        input_mod.guarded_click(hwnd, sp[0], sp[1], dry_run=False, log=log)
        time.sleep(1.5)
        _, frame = grab(state, strict=True, log=log)
        shot(state, frame, f"nte-nav-attempt{attempt}", log)

    raise GuardFailure(
        "INV-24",
        f"ok-nte 导航 {NAV_RETRIES} 次后仍未进入日常任务页。\n"
        f"  => 可能原因：界面改版、点击落空、或当前不在可导航的页面。")


def nte_locate_start_button(state, frame, log, offline=False):
    """ok-nte 定位「开始」按钮并换算屏幕坐标。

    返回 (screen_coords, loc)。
    """
    log("\n[8b] 定位任务页与「开始」按钮（ok-nte）")
    loc = nte_locate_start(frame.rgb, log=log)
    btn = loc["button"]
    bx0, by0, bx1, by1 = btn["box"]
    cx, cy = btn["center"]
    log(f"  已勾选任务 {loc['n_checked']} 项；行中心 = "
        f"{[round(b['cy']) for b in loc['boxes']]}")
    log(f"  开始按钮 窗口内 x={bx0}..{bx1} y={by0}..{by1} 中心=({cx},{cy})")

    h, w = frame.rgb.shape[:2]
    if not (cx > w * 0.5 and cy > h * 0.8):
        raise GuardFailure(
            "INV-19",
            f"交叉验证失败：ok-nte 的「开始」应在右下角，"
            f"实测中心 ({cx},{cy}) 不在右下象限（帧 {w}x{h}）")

    # ⚠️ 离线判定要看 offline 形参，**不能只看 hwnd 是否存在**：
    # --offline 时 state 里可能残留上一次运行的 hwnd，对它调 ClientToScreen
    # 会失败并报 INV-23，把「离线定位其实已经成功」伪装成失败（实测踩过）。
    hwnd = None if offline else state.get("hwnd")
    if hwnd:
        sp = win32.client_to_screen(hwnd, cx, cy)
        if sp is None:
            raise GuardFailure("INV-23", "ClientToScreen 失败")
        log(f"  屏幕坐标 = ({sp[0]},{sp[1]})")
    else:
        sp = (cx, cy)
        log(f"  [离线] 无窗口，窗口内坐标 = ({cx},{cy})")
    return sp, loc




def wait_for_nte_completion(state, args, log, window_log=None):
    """ok-nte 的等待完成：**看日志**，不看画面（HANDOFF §6 / FRAMEWORK §0.1）。

    ## 为什么 ok-nte 不能用 ok-ww 那套

    ok-ww 把终态**画在界面上**（完成帧 `exit_notice`），所以它必须读画面。
    ok-nte 反过来：它把终态**写进日志**
    （`TaskExecutor:Successfully Executed Task, Exiting Game and App!`），
    且游戏 `HTGame.exe` 全屏时屏幕抓图**必然全黑**（INV-13 会拒绝）——
    读画面在 ok-nte 上既不可靠也无必要。

    ## ★ 为什么用 LogWindow（字节偏移）而不是「按 ok:quit app 分段」

    若上一次运行被**外部强制终止**（本框架的兜底清理正是如此），
    它不会写 `ok:quit app` ⇒ 相邻两次运行被**合并成一段** ⇒
    新一次运行**借用上一次的成功汇总**，实测在点击后 **1 秒**就报 SUCCESS
    —— 假阳性，且**不报任何错**。按字节偏移切窗口与上一次如何收尾无关。

    ## 判定只看「是否完成」

    用户明确要求（m01268）：**个别任务失败与本项目无关，只看是否完成**。
    失败详情另行取出打印，不参与判定。

    ## ★ window_log 必须**在点击之前**武装（FAULT #25）

    原实现把 `_default_log_window()` 放在本函数里构造，而本函数是在
    `click_and_confirm` **之后**才被调用的 ⇒ 基线偏移取在点击之后 ⇒
    点击与构造之间 ok-nte 写的任何日志**全部读不到**。
    实测：ok-nte 点开始后 1 秒内就写了大量启动日志（甚至可能写终止标记），
    而 `LogWindow()` 此时才构造，`text()` 恒为 0 ⇒ verdict 恒 `unknown`
    ⇒ 整条 ok-nte 链**永远等不到完成**，且**不报错**。
    修法：由调用方在点击**前**构造并 `mark()`，再传进来复用（形参 window_log）。
    未传时退回在本函数内构造（保持向后兼容，但会打印警告）。
    """
    log(f"\n[8e] 等待完成（ok-nte 日志判据）：采样 {POLL_INTERVAL}s；"
        f"兜底 {args.total_timeout:.0f}s")
    log(f"  日志窗口 {NTE_LOGDIR}")

    if window_log is None:
        log("  [!!] 未提供预武装的 LogWindow —— 基线偏移取在点击之后，"
            "点击到此刻之间的日志会丢失（FAULT #25）")
        window_log = _default_log_window()
    else:
        log(f"  日志窗口已预武装（点击前建立），当前已捕获 {len(window_log.text())} 字符")
    started = time.time()
    last_report = 0.0
    last_alive = True
    stall_since = None

    while True:
        now = time.time()
        elapsed = now - started

        if elapsed > args.total_timeout:
            return TIMEOUT, f"整条链超过兜底上限 {args.total_timeout:.0f}s", None

        window_log.poll()
        alive = bool(window.running(program=programs_mod.NTE))
        last_alive = alive
        v, ev = window_log.verdict(still_running=alive)

        # ⚠️ FAULT #30：执行器永久暂停时必须**提前**报出来，不能空等到超时。
        # 游戏窗口被最小化时 ok-nte 写下 og.executor.pause pos_invalid(-32000,...)
        # 然后停住：进程还在、终止标记永远不来 ⇒ 循环会一路轮询到
        # --total-timeout（默认 1800s）才报 TIMEOUT，**白烧半小时且归因错误**。
        # 这里改成：先等一个宽限期（给它自行恢复的机会，实测有时能恢复），
        # 之后若仍无任何进展就直接判定为 STALLED 并说清原因。
        paused, why = nte_executor_paused(window_log.text())
        if paused:
            if stall_since is None:
                stall_since = now
                log(f"  [注意] {why}")
                log(f"  [注意] 给它 {args.stall_grace:.0f}s 自行恢复"
                    f"（实测恢复窗口有时有效、有时无效）…")
            elif now - stall_since > args.stall_grace:
                return STALLED, (f"ok-nte 执行器已暂停 {now - stall_since:.0f}s 无任何进展"
                                 f"：{why}"), None
        else:
            if stall_since is not None:
                log("  [OK] 执行器已恢复（继续等待）")
            stall_since = None

        if v == SUCCESS:
            # ⚠️ FAULT #27：**先让它自己收尾，别急着宣布完成**。
            #
            # ok-nte 的终止标记是「**将要**退出」的宣告，不是「已经退出」。
            # 实测 10-15 那次：终止标记 00:23:15.570 → 真正开始杀游戏
            # 00:23:20.571（+5.0s）→ `ok:quit app` 00:23:25.646（+10.1s）。
            # 若一见到标记就返回，节点 9 会在 1 秒内杀掉 ok-nte，
            # **正好打断它关游戏的那一步** ⇒ 游戏成了孤儿进程（全屏盖住一切）。
            # 本轮实测就是这么发生的：标记 02:54:06.809，节点 9 在 0.8s 后动手，
            # 日志停在标记那一行，`Killing process(es)` 一行都没写出来。
            #
            # 所以：给一段**有界**的 settle 窗口，等它把关闭动作做完。
            # 判据是「它自己退出」，不是「等到日志不再增长」——
            # 后者会被无关日志拖住。超时就继续往下走（尽量干净，但不无限等）。
            # ⚠️ 只认 **settle 期间新增** 的日志：`poll()` 的返回值就是本次新增，
            # 不能用 `text()` —— 后者返回**整轮累积**文本，会把本轮的任意一行
            # 当成「刚刚关的游戏」（范围比判据意图大得多）。
            settle_deadline = time.time() + NTE_SETTLE_SECONDS
            new_text = ""
            while time.time() < settle_deadline:
                new_text += window_log.poll()
                if not window.running(program=programs_mod.NTE):
                    break
                time.sleep(POLL_INTERVAL)

            settled = not bool(window.running(program=programs_mod.NTE))
            new_text += window_log.poll()
            if re.search(NTE_KILL_GAME, new_text, re.I):
                log("  [OK] ok-nte 已自行关闭游戏")
            elif settled:
                # 没看到关游戏的日志，但它确实退干净了。
                # 不报「已关游戏」——日志里没有证据（INV-30）。
                log("  [注意] ok-nte 已自行退出，但日志中未见关闭游戏的记录；"
                    "游戏可能仍在运行，请人工确认")
            else:
                log(f"  [注意] 等了 {NTE_SETTLE_SECONDS:.0f}s ok-nte 仍未退出，"
                    "将交由节点 9 清理")

            log(f"  +{elapsed:6.0f}s  *** 完成 ***（ok-nte 日志判据）")
            for e in ev:
                log(f"      {e}")
            fails = window_log.failures()
            if fails:
                # 失败项**不影响判定**，但必须让人看见（用户要求）。
                log(f"  [注意] 本次有 {len(fails)} 项子任务失败（不影响完成判定）："
                    f"{fails}")
            else:
                log("  [OK] 无子任务失败")
            state.set("verdict_evidence", ev)
            return COMPLETED, "；".join(ev), None

        if not alive and elapsed > POLL_INTERVAL * 2:
            # 进程没了但日志里没有终止标记 —— 分不清「无事可做而异常退出」
            # 与「崩溃」，按 INV-30 报 unknown，绝不默认成功。
            log(f"  +{elapsed:6.0f}s  ok-nte 进程消失（日志中无终止标记）")
            for e in ev:
                log(f"      {e}")
            return UNKNOWN, (
                "ok-nte 进程消失，但日志中从未出现终止标记 —— 无法区分"
                "「今日任务已完成、无事可做」与「崩溃」。这是证据不足，"
                "不是判定失败。请人工核对 ok-nte 任务日志。"), None

        if now - last_report > 30:
            last_report = now
            log(f"  +{elapsed:6.0f}s  … 仍在运行 "
                f"（日志 {len(window_log.text())} 字节）")

        time.sleep(POLL_INTERVAL)


