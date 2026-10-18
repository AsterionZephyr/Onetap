"""节点 8：任务循环（README §5 步骤 [4] [5] [6] [7]）

本节点把 README §5 的四步收在一份代码里，因为它们**共用一个闭环**：
导航 -> 定位 -> 点击 -> 验证 -> 等待完成。拆开反而会切断"点击落空就重试整轮"的逻辑。

内部按小阶段推进（每段都打印独立标题，便于定位出错位置）：

    8a  导航    若不在任务页，点侧栏图标过去；点击后**重新抓帧闭环验证**
    8b  定位    定位「每日任务」行 -> 扫描同行「开始」按钮 -> 交叉验证
    8c  点击    动作前置关（屏幕内 + 前台 + 目标顶层）-> 真实光标点击
    8d  验证    点击后帧差异 >= 阈值才算生效；否则**重试整轮**（N=3）
    8e  等待    轮询完成帧 / 计时器冻结，直到完成 / 超时 / 失败

终止行为四分（HANDOFF §6）——**必须区分**，因为随后的清理行为完全不同：

    完成    抓到完成帧，ok-ww 自行退出          -> 不杀任何进程
    超时    计时器冻结 180s（ok-ww 在等游戏）   -> 走清理路径
    失败    点击后连续无变化 / 抓帧被拦          -> 走清理路径
    未决    进程消失但从未抓到完成帧            -> **报 unknown**（见下）

⚠️ **「未决」为什么不是「失败」**（FAULT #17）：

ok-ww 进程消失、而我们没抓到完成帧，有**两种无法用画面区分的成因**：

    (a) 今日任务**已完成** —— ok-ww 找不到要做的任务，会**异常退出**。
        实测行为：它既不关闭自己，也不关闭游戏，需人工收尾。
    (b) ok-ww 真的崩了。

成因 (a) 完全正常，把它报成 `failed`（= 断言「出错了」）会误导人，
也曾让我一度误判为框架缺陷。按 INV-30「证据不足报 UNKNOWN，绝不默认成功」，
这里既不能报 completed（无证据），也不该报 failed —— 报 **unknown**，
把判断交给人。日志里会同时给出两种成因供人排除。

⚠️ 当前 `exit_notice` 资产**未采集**（见 assets.json），所以「正常完成」这条
路径**判不出来**：程序会明确打印这个缺口，并以超时 / 未决收场，
不会假装成功（INV-30）。补齐 `exit_notice` 后，「未决」才能收敛为可靠的两分。

单独跑：

    python -m orchestrator.steps.step8_run_task --dry-run          # 只定位不点击
    python -m orchestrator.steps.step8_run_task                    # 真实点击 + 等待
    python -m orchestrator.steps.step8_run_task --only-locate      # 只跑 8a+8b
"""

import os
import re
import time

from .. import apps
from .. import assets as assets_mod
from .. import capture as capture_mod
from .. import input as input_mod, match, state as state_mod, win32, window
from .. import programs as programs_mod
from .. import verdict as verdict_mod
from .. import watchdog as watchdog_mod
from ..errors import GuardFailure
# 节点 8 的通用助手已下沉到 frameops（docs/adr/0003 阶段二），这里 re-export
# 是为了让旧的内部引用（本文件的既有调用点、probe/*）行为完全不变。
from ..frameops import (  # noqa: F401  (re-export)
    CLICK_BLOCK_COLS,
    CLICK_BLOCK_MIN,
    CLICK_BLOCK_ROWS,
    CLICK_PIXEL_DELTA,
    CLICK_PIXEL_FRAC,
    finish,
    frame_changed,
    grab,
    shot,
)
from ..orchestrator import (
    CHANGE_THRESHOLD, CLICK_RETRIES, CLICK_RETRY_INTERVAL, COMPLETED, FAILED,
    FREEZE_SECONDS, NAV_RETRIES, POLL_INTERVAL, STALLED, TIMEOUT, TOTAL_TIMEOUT,
    UNKNOWN,
)

from . import context


def extra_args(ap):
    ap.add_argument("--freeze-seconds", type=float, default=FREEZE_SECONDS,
                    help=f"计时器冻结多少秒后判超时（默认 {FREEZE_SECONDS:.0f}）")
    ap.add_argument("--total-timeout", type=float, default=TOTAL_TIMEOUT,
                    help=f"整条链兜底上限（秒），默认 {TOTAL_TIMEOUT:.0f}")
    ap.add_argument("--stall-grace", type=float, default=NTE_STALL_GRACE_SECONDS,
                    help="检测到执行器暂停后，再给这么多秒自行恢复；"
                         f"仍无进展则判 STALLED（默认 {NTE_STALL_GRACE_SECONDS:.0f}）。"
                         "调小它可以在不真等 90s 的情况下验证 STALLED 分支")
    ap.add_argument("--only-locate", action="store_true",
                    help="只跑 8a 导航 + 8b 定位，不点击、不等待")
    ap.add_argument("--adopt-frame", default=None,
                    help="用这张 PNG 代替首次抓帧（离线验证定位链）")
    ap.add_argument("--offline", action="store_true",
                    help="离线模式：不发现窗口、不点击，只用 --adopt-frame 验证定位链")


# ------------------------------------------------------------ 抓帧工具


# 抓帧助手已下沉到 orchestrator/frameops.py::grab（三程序共用，docs/adr/0003）


# 8a 导航（ok-ww）=> orchestrator/apps/ww.py::navigate_to_tasks


# 8a/8b（ok-nte）=> orchestrator/apps/nte.py::nte_wait_game_settled / nte_navigate_to_daily /
#                nte_locate_start_button


# ------------------------------------------------------------ 8b 定位


# 8b 定位（ok-ww）=> orchestrator/apps/ww.py::locate_and_click_start


# ------------------------------------------------- 8c/8d 点击 + 验证


# --- FAULT #23：点击生效判据必须**看得见局部响应** -------------------------
#
# 原来只看「整帧平均像素差 >= CHANGE_THRESHOLD(0.5)」，这在 ok-nte 上**必然误判**：
# 实测点「开始」后 ok-nte 只弹一个顶部 toast「启动成功」，占全帧 0.5% 像素，
# 整帧平均差只有 **0.153**（< 0.5）⇒ 判「画面几乎未变」⇒ 白烧 3 次重试。
# 而那次点击**真的成功了**（日志随即出现 LauncherTask 启动游戏的记录）。
#
# 教训与 match.find_menu_glyph 那次同型：**把「全帧统计量」当「事件发生」的判据**，
# 对「局部变化」不敏感。改为分块看**最大块差**，并辅以「有多少像素真的变了」。
#
# 实测本次样本：最大块差 3.20（块 行0列3，就是那条 toast）；变化>10 的像素 0.5%。
# FAULT #23 的判据常量（CLICK_BLOCK_* / CLICK_PIXEL_*）与 frame_changed()
# 一起下沉到 orchestrator/frameops.py —— apps/*.py 也要用，不能留在节点 8 里。

# ok-nte 的等待常量与 8e 实现 => orchestrator/apps/nte.py（NTE_SETTLE_SECONDS 等）


def click_and_confirm(state, frame, registry, args, log, prog=None):
    """点击「开始」并验证生效；无变化则**重试整轮**（Q8：N=3）。

    重试时重新置前台、重新定位、重新点击 —— 因为 ok-ww 会自己移动鼠标
    （MouseResetTask，日志 125 处 `move mouse back`），点击后若依赖光标位置需重新确认。

    prog 给定时按目标程序分派导航/定位（ok-nte 的任务页结构与 ok-ww 不同构）。
    """
    for attempt in range(1, CLICK_RETRIES + 1):
        log(f"\n[8c] 点击 第 {attempt}/{CLICK_RETRIES} 轮")
        if prog is not None and prog.key == "nte":
            nte_app = apps.get("nte")
            if attempt == 1 and not (args.offline or args.dry_run):
                nte_app.nte_wait_game_settled(state, log)
            frame, _ = nte_app.nte_navigate_to_daily(state, frame, args, log)
            sp, _loc = nte_app.nte_locate_start_button(state, frame, log, offline=args.offline)
        else:
            ww_app = apps.get("ww")
            frame, _ = ww_app.navigate_to_tasks(state, frame, registry, args, log)
            sp, _y0, _y1, _loc = ww_app.locate_and_click_start(state, frame, registry, log)
        shot(state, frame, "about-to-click", log)

        before = frame.rgb.astype("int16")
        input_mod.guarded_click(state.get("hwnd"), sp[0], sp[1],
                                dry_run=args.dry_run, log=log)
        if args.dry_run:
            return True, frame

        log("\n[8d] 验证已启动")
        time.sleep(1.2)
        _, after = grab(state, strict=False, log=log)
        changed, why = frame_changed(before, after.rgb, log=log)
        if changed:
            log(f"  [OK] 画面已变化（{why}），点击很可能生效")
            shot(state, after, "after-click", log)
            return True, after
        log(f"  [!!] 画面几乎未变（{why}）—— 点击可能落空"
            f"（ok-ww 失焦会静默挂起）")
        shot(state, after, f"no-change-try{attempt}", log)
        if attempt < CLICK_RETRIES:
            log(f"  等待 {CLICK_RETRY_INTERVAL:.0f}s 后重试整轮")
            time.sleep(CLICK_RETRY_INTERVAL)

    return False, frame


# --------------------------------------------------------- 8e 等待完成


# 8e 等待（ok-nte）=> orchestrator/apps/nte.py::wait_for_nte_completion


# 8e 等待（ok-ww）=> orchestrator/apps/ww.py::wait_for_completion


# ------------------------------------------------ 8b~8e：MaaEnd（zmd）
#
# MaaEnd 的 8b~8e **整段**已迁到 orchestrator/apps/zmd.py（docs/adr/0003）：
#   zmd_locate / zmd_click_and_confirm / zmd_wait_completion / zmd_run
# 这里只剩一行分派（见 body()）。三段结构差异（单页 / 单层 / 只能读日志判完成）
# 与「运行期为什么不能抓帧」的长注释也随代码一起搬走了。
#
# finish()（result -> 状态码的唯一映射）下沉到 orchestrator/frameops.py，
# 因为所有程序都要用；shot()/frame_changed() 同处。


# ------------------------------------------------------------- 主流程


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    registry = assets_mod.Registry()

    # 取首帧：可注入（离线调试），否则实时抓
    if args.adopt_frame:
        from .step6_first_frame import load_rgb
        from ..capture import Frame
        rgb = load_rgb(args.adopt_frame)
        h, w = rgb.shape[:2]
        # 离线模式**不需要窗口**：--only-locate 只验证定位链，坐标只是换算结果。
        # 若恰好有窗口就拿它的原点，否则按 (0,0) 记 —— 定位结论与原点无关。
        hwnd = context.rediscover_hwnd(state, log=None) if not args.offline else None
        st = (win32.window_state(hwnd) if hwnd else None) or {"left": 0, "top": 0}
        f = Frame(rgb, (st["left"], st["top"], st["left"] + w, st["top"] + h),
                  (w, h), {"mean_rgb": (0, 0, 0), "distinct_colors_sampled": 0})
        log(f"  [注入] 用 {args.adopt_frame} 代替抓帧 {w}x{h}")
        if hwnd:
            log(f"  窗口 hwnd={hwnd} 原点=({st['left']},{st['top']})")
        else:
            log("  [离线] 无窗口：屏幕坐标按原点 (0,0) 换算，仅供相对定位参考")
    else:
        hwnd = context.require_hwnd(state, log=log)
        try:
            f = capture_mod.grab_frame(hwnd, strict_content=True)
        except GuardFailure as e:
            return "failed", {"invariant": e.invariant}, \
                f"抓帧失败 {e.invariant}：{e.detail.splitlines()[0]}"
        log(f"  首帧 {f.width}x{f.height} 均值RGB={f.stats['mean_rgb']}")
        shot(state, f, "task-loop-start", log)

    # ★ MaaEnd 走**整段独立实现**（单页 / 单层 / Tauri 窗口类 / 日志判据），
    # 在 8a 之前分派：它没有任务页要导航，若落进下面的 ok-ww 定位链，
    # 第一步侧栏图标匹配就会失败 —— 而失败信息会指向「找不到侧栏」，
    # 与真正的问题（这个程序没有侧栏）完全无关，把人引到错方向。
    if prog.key == "zmd":
        try:
            # 入口唯一：实现只在 orchestrator/apps/zmd.py（docs/adr/0003）。
            # apps.get 对未迁移的程序抛 KeyError 而不是回落 —— 回落会让人以为
            # 改了专项模块，其实改的是共用文件。
            return apps.get("zmd").zmd_run(state, args, f, log)
        except GuardFailure as e:
            log(f"\n  [!!] [{e.invariant}] {e.detail}")
            return "failed", {"invariant": e.invariant}, \
                f"{e.invariant}：{e.detail.splitlines()[0]}"

    # --- 8a + 8b（--only-locate 到此为止）---------------------------------
    # ⚠️ 两个程序的任务页**不同构**，定位链必须分派（FAULT #22）：
    #   ok-ww  -> 单行「每日任务」+ 行内扫描最右亮像素 = 开始按钮
    #   ok-nte -> 多行复选列表 + 右下角唯一「开始」按钮
    if args.only_locate:
        try:
            if prog.key == "nte":
                nte_app = apps.get("nte")
                f, _nav = nte_app.nte_navigate_to_daily(state, f, args, log)
                sp, loc = nte_app.nte_locate_start_button(state, f, log, offline=args.offline)
                y0 = y1 = 0
            else:
                ww_app = apps.get("ww")
                f, _nav = ww_app.navigate_to_tasks(state, f, registry, args, log)
                sp, y0, y1, loc = ww_app.locate_and_click_start(state, f, registry, log)
        except GuardFailure as e:
            log(f"\n  [!!] [{e.invariant}] {e.detail}")
            return "failed", {"invariant": e.invariant}, \
                f"{e.invariant}：{e.detail.splitlines()[0]}"
        shot(state, f, "located", log)
        if prog.key == "nte":
            return ("ok",
                    {"mode": "only-locate", "program": prog.key,
                     "screen_coords": list(sp),
                     "n_checked": loc["n_checked"],
                     "boxes": [round(b["cy"], 1) for b in loc["boxes"]],
                     "button_center": list(loc["button"]["center"]),
                     "offline": bool(args.adopt_frame)},
                    f"定位成功（ok-nte）已勾选 {loc['n_checked']} 项 "
                    f"按钮窗口内 {tuple(loc['button']['center'])}")
        return ("ok",
                {"mode": "only-locate", "screen_coords": list(sp),
                 "row_y0": y0, "row_y1": y1,
                 "anchor_score": loc["anchor"]["score"],
                 "button_center": list(loc["button"]["center"]),
                 "offline": bool(args.adopt_frame)},
                f"定位成功 锚点 {loc['anchor']['score']:.4f} "
                f"按钮窗口内 {tuple(loc['button']['center'])}")

    # --- 8c + 8d ---------------------------------------------------------
    #
    # ★ FAULT #25：日志窗口必须**在点击之前**武装。
    # 基线偏移若取在点击之后，点击到构造之间程序写的日志全部丢失 ——
    # 实测 text() 恒为 0、verdict 恒 unknown、整条链永远等不到完成且不报错。
    #
    # ★ FAULT #15：ok-ww **也要**武装。它同样写那句共用的终止标记，
    # 过去只认 ok-nte 的目录（还默认错指到不存在的路径），于是 ok-ww 只能靠
    # 那幅从未采集的完成帧、以「超时」收场。
    prog_log_window = verdict_mod.LogWindow(program=prog)
    log(f"\n[8e-预备] 已武装 {prog.display} 日志窗口（点击前），"
        f"目录 {prog_log_window.logdir}，"
        f"基线 {len(prog_log_window._files())} 个日志文件")

    try:
        ok, f = click_and_confirm(state, f, registry, args, log, prog=prog)
    except GuardFailure as e:
        log(f"\n  [!!] [{e.invariant}] {e.detail}")
        return "failed", {"invariant": e.invariant}, \
            f"{e.invariant}：{e.detail.splitlines()[0]}"

    if args.dry_run:
        log("\n[DRY RUN] 汇总")
        log("  [OK] 节点 1~7 全部通过（提权自检按参数处理）")
        log("  [OK] 抓帧 / 尺寸校验 / 内容校验 / 身份校验 全部通过")
        log("  [OK] 置前台 + 可用性校验 通过")
        log("  [OK] 动作前置关通过（屏幕内 + 前台 + 目标顶层判定）")
        log("  [!!] 未实际点击 —— dry-run 到此为止")
        state.set("result", COMPLETED)
        return "ok", {"mode": "dry-run", "result": COMPLETED}, "dry-run 汇总通过"

    if not ok:
        return ("failed",
                {"invariant": "INV-8", "result": FAILED},
                f"连续 {CLICK_RETRIES} 轮点击后画面无变化 —— ok-ww 很可能失焦静默挂起")

    # --- 8e --------------------------------------------------------------
    # 判据按**目标程序**分派（HANDOFF §6）。两程序**都走日志判据**：
    #   ok-nte -> 终止标记 + 逐项汇总 success/failed/skipped
    #   ok-ww  -> 终止标记（FAULT #15：实测它写的是**逐字相同**的那句话）
    # ok-ww 侧不再依赖画面完成帧；抓帧仍保留，作为超时时落盘取证。
    if prog.key == "nte":
        result, detail, frame_path = apps.get("nte").wait_for_nte_completion(
            state, args, log, window_log=prog_log_window)
    else:
        result, detail, frame_path = apps.get("ww").wait_for_completion(
            state, registry, args, log, window_log=prog_log_window)
    # result -> 状态码的映射**只有一处**（finish()），zmd 与主流程共用，
    # 避免两条路径的映射表日后各自漂移。
    return finish(state, result, detail, frame_path, log)


# ---------------------------------------------------------------------------
# 旧调用点垫片：实现已迁到 orchestrator/apps/<key>.py（docs/adr/0003），
# probe/ 下的探针仍按 step8.<名字> 取用（同一个函数对象，不是副本）。
# ---------------------------------------------------------------------------
from ..apps.nte import (  # noqa: E402,F401
    NTE_GAME_WAIT_SECONDS,
    NTE_READABLE_SAMPLES,
    NTE_SETTLE_POLL,
    NTE_SETTLE_SECONDS,
    NTE_STALL_GRACE_SECONDS,
    nte_locate_start_button,
    nte_navigate_to_daily,
    nte_wait_game_settled,
    wait_for_nte_completion,
)
from ..apps.ww import (  # noqa: E402,F401
    locate_and_click_start,
    navigate_to_tasks,
    wait_for_completion,
)


if __name__ == "__main__":
    raise SystemExit(context.run_step("8", "run_task", body, extra_args))
