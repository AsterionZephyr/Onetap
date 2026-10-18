"""ok-ww 专项模块 —— 定位、判据、节点 8 的 ok-ww 实现。

**归属规则（docs/adr/0003）**：改 ok-ww 的行为只改本文件；共用层
（match.py / verdict.py / steps/step8_run_task.py）只按需惰性 import 本模块，
反向不行 —— 共用层用 PEP 562 的 __getattr__ 垫片转出旧名字，避免成环。

内容来源（2026-10-19 搬迁，逐行切片，无改写）：
  - 定位：orchestrator/match.py 的 verify_identity / scan_row_button / locate_daily_row
  - 判据：orchestrator/verdict.py 的 WW_DAILY_END / WW_KILL_GAME / ww_verdict
  - 节点 8：orchestrator/steps/step8_run_task.py 的 navigate_to_tasks /
    locate_and_click_start / wait_for_completion
"""
import os
import re
import time

import numpy as np

from .. import capture as capture_mod
from .. import input as input_mod
from .. import match as match_mod
from .. import programs as programs_mod
from .. import state as state_mod
from .. import verdict as verdict_mod
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

# 被搬来的函数体按**原文件里的裸名字**引用共用内核（模板匹配、☰/侧栏检测、前台与
# 动作前置关、窗口/进程查询）。这里把同一批对象绑到本模块，等价于它们在原文件里的
# 可见性 —— 不复制实现，仍是同一个函数对象。
ACCEPT = match_mod.ACCEPT
IDENTITY_MIN = match_mod.IDENTITY_MIN
MENU_CORNER_H_FRAC = match_mod.MENU_CORNER_H_FRAC
MENU_CORNER_W_FRAC = match_mod.MENU_CORNER_W_FRAC
SIDEBAR_ITEM_TASKS = match_mod.SIDEBAR_ITEM_TASKS
SIDEBAR_TOL = match_mod.SIDEBAR_TOL
SIDEBAR_X = match_mod.SIDEBAR_X
SIDEBAR_Y = match_mod.SIDEBAR_Y
WARN = match_mod.WARN
crop_anchor = match_mod.crop_anchor
find_menu_glyph = match_mod.find_menu_glyph
find_sidebar_item = match_mod.find_sidebar_item
local_maxima = match_mod.local_maxima
match_best = match_mod.match_best
score_map = match_mod.score_map
to_gray = match_mod.to_gray
guarded_click = input_mod.guarded_click
grab_frame = capture_mod.grab_frame
find_okww_window = window.find_okww_window
okww_running = window.okww_running
client_to_screen = win32.client_to_screen
FreezeDetector = state_mod.FreezeDetector
is_completion_frame = state_mod.is_completion_frame
WW = programs_mod.WW

# 节点 8：见到终止标记后的收尾宽限（原 step8 借用 NTE_ 常量；这里给 ok-ww 自己的名字）
WW_SETTLE_SECONDS = 20.0



# ==========================================================================
# 一、定位（原 orchestrator/match.py）
# ==========================================================================

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




# ==========================================================================
# 二、判据（原 orchestrator/verdict.py）
# ==========================================================================

# --- FAULT #15：ok-ww 的终态**同样可以从日志判定**（新增）-------------------
#
# 长期以来的记录是：ok-ww 的判定依据是**画面**（完成帧 `exit_notice`），
# 而那张图**从未采集**，于是「无法判定正常完成，只能以超时收场」，
# 被记为本项目「唯一的功能缺口」。
#
# **实测推翻了该前提。** ok-ww 与 ok-nte 是同一套 ok-script 运行时，
# 收尾写的是**逐字相同**的那句话（同一进程 TaskExecutor、同一句文案）：
#
#     2026-10-15 20:37:29,623 INFO TaskExecutor DailyTask:Daily Task Completed
#     2026-10-15 20:37:29,624 INFO TaskExecutor TaskExecutor:Successfully \
#            Executed Task, Exiting Game and App!
#     2026-10-15 20:37:34,624 INFO TaskExecutor process:Killing process(es) \
#            with absolute path: ...\Client-Win64-Shipping.exe
#
# 逐文件统计（ok-ww 全部日志）：凡**跑到完成**的次数，终止标记与「杀游戏」
# 都是**恰好各 1 次**；而 10-12/13/14 三个文件两者皆 0（那几次没跑完）。
# ok-nte 侧同样统计到 8 次。⇒ 这是**两程序共用**的终止标记，
# 差别只在目标游戏进程名（ok-ww=`Client-Win64-Shipping.exe`）。
#
# 故 ok-ww **不需要**那张完成帧截图也能判完成。`exit_notice` 图像仍可作为
# 补充证据，但不再是判定的**前置条件**。
#
# ⚠️ 两条必须保留的纪律：
#   1. 必须用 `LogWindow`（按字节偏移切窗口），不能按 `ok:quit app` 分段 ——
#      上一次被强制终止时不写 `ok:quit app`，会把两次运行合并、**借用**上一次的
#      成功标记（假阳性，实测点击后 1 秒就报 SUCCESS）。
#   2. 逐项结果 ok-ww 侧没有 ok-nte 那种 `info_set success [...]` 汇总
#      （实测 `DailyRoutineTask` 痕迹为 0），故**不解析汇总**，只用终止标记。
WW_DAILY_END = r"DailyTask:Daily Task Completed"
# 终止标记与 ok-nte 是**同一个字符串**（共用叶子常量，见 statuses.py）。
WW_TERMINAL_MARK = TERMINAL_MARK_EXIT_GAME
WW_KILL_GAME = r"Trying to kill the exe \{[^}]*Client-Win64-Shipping\.exe"


def ww_verdict(text, still_running=False):
    """对 ok-ww 的日志文本判定终态。返回 (verdict, evidence[])。

    与 `nte_verdict` 同构，只是标记名不同：

        SUCCESS  : 出现共用终止标记，**或**出现 `DailyTask:Daily Task Completed`
        RUNNING  : 无终止标记且进程仍在运行
        NO_TASK  : 无任何任务痕迹
        UNKNOWN  : 其他（**证据不足绝不报成功**，INV-30）
    """
    if not text or not text.strip():
        if still_running:
            return RUNNING, ["本次运行尚无新增日志，但进程在运行"]
        return UNKNOWN, ["日志为空（本次运行尚无新增内容）"]

    ev = []
    terminal = bool(re.search(WW_TERMINAL_MARK, text))
    daily_end = bool(re.search(WW_DAILY_END, text))
    killed = bool(re.search(WW_KILL_GAME, text, re.I))

    # ok-ww 的日常痕迹：阶段行 `info_set current task <phase>`。
    # ⚠️ 实测 ok-ww **没有** ok-nte 那种 `DailyRoutineTask:info_set success [...]`
    # 逐项汇总（`DailyRoutineTask` 计数为 0），故此处不做汇总解析 ——
    # 若照抄 ok-nte 的正则，会天天报「未解析到汇总行」的假警报。
    phases = re.findall(r"info_set current task\s+(\S+)", text)

    ev.append(f"终止标记={terminal} 日常结束={daily_end} 杀游戏={killed}")
    if phases:
        ev.append(f"阶段痕迹 {len(phases)} 条，末条={phases[-1]}")

    if not (terminal or daily_end or phases):
        if still_running:
            return RUNNING, ev + ["尚无任务痕迹，进程在运行"]
        return NO_TASK, ev + ["无任务痕迹"]

    if terminal:
        return SUCCESS, ev + ["出现终止标记（进程收尾）"]
    if daily_end:
        return SUCCESS, ev + ["日常任务结束（Daily Task Completed）"]

    if still_running:
        return RUNNING, ev + ["仍在运行"]
    return UNKNOWN, ev + ["序列不完整且无终止标记"]




# ==========================================================================
# 三、节点 8（原 orchestrator/steps/step8_run_task.py）
# ==========================================================================

def navigate_to_tasks(state, frame, registry, args, log):
    """若不在任务页，点侧栏图标导航过去。返回 (frame, navigated)。

    导航是**闭环**的：点击后重新抓帧并验证目标行是否出现，因为真实光标点击有
    落空的可能（窗口失焦时 ok-ww 会静默挂起而不报错）。

    ⚠️ 侧栏图标位置**不硬编码**：它由资产匹配得出（实测恒在窗口内 (16,215)，
    但 215 这个 y 是 1822x1000 帧实测值，换尺寸先验证再说）。
    """
    log("\n[8a] 导航：确认当前在任务页")
    row_tpl = registry["daily_row"].load()

    for attempt in range(1, NAV_RETRIES + 1):
        try:
            locate_daily_row(frame.rgb, row_tpl)
            if attempt > 1:
                log(f"  [OK] 第 {attempt} 次抓帧确认：已在任务页")
            else:
                log("  [OK] 已在任务页（锚点可唯一定位）")
            return frame, attempt > 1
        except GuardFailure as e:
            log(f"  第 {attempt} 次判定：当前页没有目标行 —— "
                f"{e.detail.splitlines()[0]}")

        if attempt >= NAV_RETRIES:
            break

        # 离线 / dry-run：不点击，直接把"当前页不在任务页"作为结论返回，
        # 交给 --only-locate 的定位环节去暴露锚点问题（这正是离线调试想要的）。
        if args.offline or args.dry_run:
            log("  [离线/DRY RUN] 不点击导航；直接进入定位环节以检验锚点")
            return frame, False

        log("  点击侧栏「任务」图标导航")
        # ⚠️ 绝不可复用 verify_identity 的 pos 当导航目标。
        # `1_ww.png` 曾同时承担「身份锚点 + 导航目标」两个职责，那个复用
        # 在改造前恰好成立；身份锚点改成 ☰ 检测后，pos 变成 ☰ 的位置，
        # 于是导航**点到了 ☰**，页面永远不切换（实测连点 3 次仍停在「关于」页，
        # 且不报错 —— 典型静默失效）。见 match.find_sidebar_item 的注释。
        item = match_mod.find_sidebar_item(frame.rgb, SIDEBAR_ITEM_TASKS,
                                          log=log)
        if item is None:
            raise GuardFailure(
                "INV-24",
                "无法程序化定位侧栏「任务」项（侧栏等距列表未识别）。\n"
                "  => 可能原因：侧栏未展开、界面改版、或窗口尺寸不在预期范围。")
        cx, cy = item["pos"]
        hwnd = state.get("hwnd")
        if not hwnd:
            raise GuardFailure("INV-23", "导航需要窗口句柄，但当前没有（离线模式请加 --only-locate）")
        sp = win32.client_to_screen(hwnd, cx, cy)
        if sp is None:
            raise GuardFailure("INV-23", "ClientToScreen 失败")
        log(f"  侧栏「任务」为第 {SIDEBAR_ITEM_TASKS} 项"
            f"（共 {item['n_items']} 项，行距 {item['pitch']}px），"
            f"窗口内点=({cx},{cy}) -> 屏幕 ({sp[0]},{sp[1]})")
        input_mod.guarded_click(hwnd, sp[0], sp[1],
                                dry_run=False, log=log)
        time.sleep(1.5)
        _, frame = grab(state, strict=True, log=log)
        shot(state, frame, f"nav-attempt{attempt}", log)

    raise GuardFailure(
        "INV-24",
        f"导航 {NAV_RETRIES} 次后仍未进入任务页（锚点始终无法唯一定位）。\n"
        f"  => 可能原因：ok-ww 版本升级导致界面改版（锚点需重新采集）、"
        f"点击落空、或当前不在可导航的页面。")




def locate_and_click_start(state, frame, registry, log):
    """定位「每日任务」行 -> 扫描同行「开始」按钮 -> 交叉验证。

    返回 (screen_coords, row_y0, row_y1, loc)。
    """
    log("\n[8b] 定位「每日任务」行")
    asset = registry["daily_row"]
    row_tpl = asset.load()

    # INV-4：出生尺寸校验。行模板是局部截图，不能要求与窗口同尺寸，
    # 故只在登记了出生尺寸且明显不同源时告警，不阻断。
    same, why = asset.check_born_size(frame.width, frame.height)
    log(f"  出生尺寸：{why}")
    if not same:
        log(f"    [警告] 资产与当前帧不同源 —— 锚点分数可能偏低，"
            f"必要时用 refresh_assets.py 重采")

    loc = locate_daily_row(frame.rgb, row_tpl)
    a = loc["anchor"]
    log(f"  锚点「日历图标+每日任务」score={a['score']:.4f} "
        f"pos={a['pos']} 尺寸={a['size'][0]}x{a['size'][1]}")
    log(f"  联合唯一性：{len(loc['candidates'])} 个候选，"
        f"1 个同时满足「同行有开始按钮」-> [OK]")

    row_y0, row_y1 = loc["row_y0"], loc["row_y1"]
    btn = loc["button"]
    bx0, by0, bx1, by1 = btn["box"]
    cx, cy = btn["center"]
    log(f"  行范围 y={row_y0}..{row_y1}")
    log(f"  开始按钮 窗口内 x={bx0}..{bx1} y={by0}..{by1} 中心=({cx},{cy})")

    if not (row_y0 <= cy <= row_y1):
        raise GuardFailure(
            "INV-19",
            f"交叉验证失败：按钮中心 y={cy} 不在行 {row_y0}..{row_y1} 内")

    hwnd = state.get("hwnd")
    if hwnd:
        sp = win32.client_to_screen(hwnd, cx, cy)
        if sp is None:
            raise GuardFailure("INV-23", "ClientToScreen 失败")
        log(f"  屏幕坐标 = ({sp[0]},{sp[1]})")
    else:
        # 离线：没有窗口，窗口内坐标就是最终结论
        sp = (cx, cy)
        log(f"  [离线] 无窗口，窗口内坐标 = ({cx},{cy})（未经 ClientToScreen 换算）")
    return sp, row_y0, row_y1, loc




def wait_for_completion(state, registry, args, log, window_log=None):
    """等待完成 / 超时。返回 (result, detail, shot_path)。

    判据（**FAULT #15 更正后**）：主判据是 **ok-ww 的日志终止标记**，
    画面（完成帧 `exit_notice`）降为**补充证据**。

    为什么改：长期记录说 ok-ww 只能看画面，而那幅完成帧从未采集，
    于是节点 8 「只能以超时收场」。实测推翻 —— ok-ww 与 ok-nte 同属
    ok-script 运行时，收尾写的是**逐字相同**的
    `TaskExecutor:Successfully Executed Task, Exiting Game and App!`，
    且凡跑到完成的运行都**恰好写一次**（见 verdict.ww_verdict 的注释）。
    ⇒ 不需要那张截图也能判完成。

    仍然**宁可漏判**（退回超时），**不可误判** —— 误判会把一次卡死当成成功。
    """
    if window_log is not None:
        log(f"\n[8e] 等待完成（ok-ww 日志判据）：采样 {POLL_INTERVAL}s；"
            f"冻结判定 {args.freeze_seconds:.0f}s；兜底 {args.total_timeout:.0f}s")
        log(f"  日志窗口 {window_log.logdir}")
        log(f"  日志窗口已预武装（点击前建立），当前已捕获 "
            f"{len(window_log.text())} 字符")
    else:
        log(f"\n[8e] 等待完成：采样 {POLL_INTERVAL}s；"
            f"冻结判定 {args.freeze_seconds:.0f}s；兜底 {args.total_timeout:.0f}s")

    exit_tpl = None
    exit_asset = registry.get("exit_notice")
    if exit_asset and exit_asset.available:
        exit_tpl = exit_asset.load()
    if window_log is None and exit_tpl is None:
        log("  [警告] 退出通知资产未采集，且未武装日志窗口 —— "
            "无法判定「正常完成」，本节点只能以「超时」收场")
    elif exit_tpl is None:
        log("  [注] 退出通知资产仍未采集；改用**日志终止标记**判定完成"
            "（FAULT #15：ok-ww 与 ok-nte 共用同一句终止标记）")

    detector = state_mod.FreezeDetector(args.freeze_seconds)
    started = time.time()
    last_fp = None
    completion_seen = False
    last_report = 0.0
    last_verdict = None

    while True:
        now = time.time()
        elapsed = now - started

        if elapsed > args.total_timeout:
            return TIMEOUT, f"整条链超过兜底上限 {args.total_timeout:.0f}s", None

        # --- 主判据：日志终止标记（FAULT #15）---
        if window_log is not None:
            window_log.poll()
            v, vev = window_log.verdict(still_running=window.okww_running(),
                                        program=programs_mod.WW)
            if v != last_verdict:
                log(f"  +{elapsed:6.0f}s  日志判据：{v}（{vev[-1] if vev else ''}）")
                last_verdict = v
            if v == verdict_mod.SUCCESS:
                log(f"  +{elapsed:6.0f}s  *** 完成 ***（ok-ww 日志终止标记）")
                for e in vev:
                    log(f"        {e}")
                # 收尾宽限（与 ok-nte 同策略，FAULT #27）：终止标记是
                # 「**将要**退出」的宣告，随后它才去关游戏、关自己。
                # 抢在这中间动手会打断它关游戏。
                settle_end = time.time() + WW_SETTLE_SECONDS
                while time.time() < settle_end:
                    window_log.poll()
                    if not window.okww_running():
                        break
                    time.sleep(POLL_INTERVAL)
                window_log.poll()
                if re.search(verdict_mod.WW_KILL_GAME, window_log.text(), re.I):
                    log("  [OK] ok-ww 已自行关闭游戏")
                elif not window.okww_running():
                    log("  [注意] ok-ww 已自行退出，但日志中未见关闭游戏的记录；"
                        "游戏可能仍在运行，请人工确认")
                else:
                    log(f"  [注意] 等了 {WW_SETTLE_SECONDS:.0f}s ok-ww 仍未退出，"
                        "将交由节点 9 清理")
                return COMPLETED, "日志出现终止标记：" + "；".join(vev), None

        # ok-ww 进程没了 —— 分三种，**必须区分**（见文件头「终止行为三分」）
        if not window.okww_running():
            if completion_seen:
                return COMPLETED, "ok-ww 已自行退出（此前抓到完成帧）", None
            # 再给日志一次机会：进程刚退，收尾那几行可能才落盘
            if window_log is not None:
                window_log.poll()
                v2, vev2 = window_log.verdict(still_running=False,
                                              program=programs_mod.WW)
                if v2 == verdict_mod.SUCCESS:
                    log(f"  +{elapsed:6.0f}s  *** 完成 ***"
                        f"（进程已退出，由日志确认）")
                    return COMPLETED, "日志出现终止标记：" + "；".join(vev2), None
            # 消失但没抓到完成帧 —— **成因不可辨**：
            #   (a) 今日任务已完成 -> ok-ww 无事可做而异常退出（实测行为：
            #       不关自己、不关游戏，需人工收尾）
            #   (b) 崩溃
            # 按 INV-30 报 UNKNOWN，**不默认成功、也不武断出错**。
            log(f"  +{elapsed:6.0f}s  ok-ww 进程消失（日志中也没有终止标记）")
            return UNKNOWN, (
                "ok-ww 进程消失，但日志中没有终止标记 —— 无法区分「今日任务已完成、"
                "无事可做而异常退出」与「崩溃」。这是证据不足，不是判定失败。"
                "常见成因：今日任务此前已完成（ok-ww 找不到要做的任务会异常退出，"
                "且不会关闭自己与游戏）。"
            ), None

        info = window.find_okww_window()
        if not info:
            time.sleep(POLL_INTERVAL)
            continue
        state.set("hwnd", info["hwnd"])   # INV-14：每轮重新发现

        try:
            f = capture_mod.grab_frame(info["hwnd"], strict_content=False)
        except GuardFailure as e:
            log(f"  [{e.invariant}] 本轮抓帧失败：{e.detail}")
            time.sleep(POLL_INTERVAL)
            continue

        fp = float(f.rgb[::40, ::40].mean())
        if last_fp is None or abs(fp - last_fp) > 0.5:
            log(f"  +{elapsed:6.0f}s  画面指纹 {fp:.2f}  {f.width}x{f.height}")
            last_fp = fp

        if exit_tpl is not None:
            ok, detail = state_mod.is_completion_frame(f.rgb, exit_tpl)
            if ok:
                log(f"  +{elapsed:6.0f}s  *** 完成帧 ***  {detail}")
                path = shot(state, f, "completion", log)
                completion_seen = True
                state.set("completion_frame", os.path.relpath(
                    path, state.run_dir).replace("\\", "/"))
                return COMPLETED, detail, path

        frozen, fdetail = detector.update(f.rgb, now)
        if frozen:
            log(f"  +{elapsed:6.0f}s  [超时] {fdetail}")
            path = shot(state, f, "timeout", log)
            return TIMEOUT, fdetail, path

        if now - last_report > 30:
            last_report = now
            log(f"  +{elapsed:6.0f}s  … {fdetail}")

        time.sleep(POLL_INTERVAL)


