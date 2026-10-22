"""节点 8 的**推进骨架**：导航 -> 定位 -> 点击 -> 验证 -> 等待完成。

这是**程序无关**的那一半（docs/adr/0005）。ok-ww / ok-nte / MaaEnd 的 8c/8d
（点击重试 + 画面变化判据）、dry-run 汇总、日志窗口武装、finish() 收尾
**逐字相同**；不同的是三件事，由各程序在自己的
orchestrator/apps/<key>/nodes/step8_run_task.py 里以 callable 传进来：

    navigate(state, frame, registry, args, log) -> frame
        8a 导航：不在任务页就点侧栏过去（点完自己重新抓帧闭环）
    locate(state, frame, registry, args, log) -> (screen_xy, info)
        8b 定位：定位「开始」按钮，返回屏幕坐标 + 要写进 state 的证据 dict
    wait(state, registry, args, log, window_log) -> (result, detail, frame_path)
        8e 等待完成（日志窗口已由本骨架武装好，直接判）
    before_click=None
        可选的点击前置动作，每轮点击前调用（ok-nte 用它等游戏窗口稳定）
    locate_note=None
        可选：(info) -> 一句给人看的话，--only-locate 的 note

**为什么骨架不复制三份**：抓帧不变量链、点击重试、画面变化判据、日志窗口
武装、finish 映射是引擎机制。复制一份出去 = 修一个 bug 改三处，漏一处就
静默出错（ADR 0003 的原始担心，ADR 0005 再次确认）。

**MaaEnd 不走本骨架**：它没有任务页、没有侧栏、只能读日志判完成，
8b~8e 整段在 apps/zmd（zmd_run）。它的节点 8 只借用本模块的
first_frame() 与前几个 CLI 参数。
"""

import time

from ... import assets as assets_mod
from ... import capture as capture_mod
from ... import input as input_mod, win32
from ... import verdict as verdict_mod
from ...errors import GuardFailure
from ...frameops import finish, frame_changed, grab, load_rgb, shot
from ...orchestrator import (
    CLICK_RETRIES, CLICK_RETRY_INTERVAL, COMPLETED, FAILED, FREEZE_SECONDS,
    TOTAL_TIMEOUT,
)
from .. import context


# 检测到执行器暂停后，再给这么多秒自行恢复（只有 ok-nte 的 8e 真正消费它；
# 另外两个程序留着是为了命令行参数面一致）。来源：apps/nte 的实测 90s。
DEFAULT_STALL_GRACE = 90.0


def extra_args(ap, stall_grace=DEFAULT_STALL_GRACE):
    """节点 8 的 CLI 参数（三个程序同形，stall_grace 默认值可由程序覆盖）。"""
    ap.add_argument("--freeze-seconds", type=float, default=FREEZE_SECONDS,
                    help=f"计时器冻结多少秒后判超时（默认 {FREEZE_SECONDS:.0f}）")
    ap.add_argument("--total-timeout", type=float, default=TOTAL_TIMEOUT,
                    help=f"整条链兜底上限（秒），默认 {TOTAL_TIMEOUT:.0f}")
    ap.add_argument("--stall-grace", type=float, default=stall_grace,
                    help="检测到执行器暂停后，再给这么多秒自行恢复；"
                         f"仍无进展则判 STALLED（默认 {stall_grace:.0f}）。"
                         "调小它可以在不真等 90s 的情况下验证 STALLED 分支")
    ap.add_argument("--only-locate", action="store_true",
                    help="只跑 8a 导航 + 8b 定位，不点击、不等待")
    ap.add_argument("--adopt-frame", default=None,
                    help="用这张 PNG 代替首次抓帧（离线验证定位链）")
    ap.add_argument("--offline", action="store_true",
                    help="离线模式：不发现窗口、不点击，只用 --adopt-frame 验证定位链")


def first_frame(state, args, log):
    """节点 8 的首帧：可用 --adopt-frame 注入（离线调试），否则实时抓。

    返回 (frame, fail)；fail 非 None 时 frame 为 None，可直接作为节点返回值。
    """
    if not args.adopt_frame:
        hwnd = context.require_hwnd(state, log=log)
        try:
            f = capture_mod.grab_frame(hwnd, strict_content=True)
        except GuardFailure as e:
            return None, ("failed", {"invariant": e.invariant},
                          f"抓帧失败 {e.invariant}：{e.detail.splitlines()[0]}")
        log(f"  首帧 {f.width}x{f.height} 均值RGB={f.stats['mean_rgb']}")
        shot(state, f, "task-loop-start", log)
        return f, None

    from ...capture import Frame

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
    return f, None


def click_and_confirm(state, frame, registry, args, log, prog,
                      navigate, locate, before_click=None):
    """点击「开始」并验证生效；无变化则**重试整轮**（Q8：N=CLICK_RETRIES）。

    重试时重新置前台、重新定位、重新点击 —— 因为 ok-ww 会自己移动鼠标
    （MouseResetTask，日志 125 处 "move mouse back"），点击后若依赖光标
    位置需重新确认。
    """
    for attempt in range(1, CLICK_RETRIES + 1):
        log(f"\n[8c] 点击 第 {attempt}/{CLICK_RETRIES} 轮")
        if before_click is not None:
            before_click(state, args, log, attempt)
        frame = navigate(state, frame, registry, args, log)
        sp, _info = locate(state, frame, registry, args, log)
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
            f"（{prog.display} 失焦会静默挂起）")
        shot(state, after, f"no-change-try{attempt}", log)
        if attempt < CLICK_RETRIES:
            log(f"  等待 {CLICK_RETRY_INTERVAL:.0f}s 后重试整轮")
            time.sleep(CLICK_RETRY_INTERVAL)

    return False, frame


def run(state, args, log, prog, navigate, locate, wait,
        before_click=None, locate_note=None):
    """节点 8 的主流程（ok-ww / ok-nte 共用；MaaEnd 走自己的 zmd_run）。"""
    registry = assets_mod.Registry()

    frame, fail = first_frame(state, args, log)
    if fail is not None:
        return fail

    # --- 8a + 8b（--only-locate 到此为止）---------------------------------
    if args.only_locate:
        try:
            frame = navigate(state, frame, registry, args, log)
            sp, info = locate(state, frame, registry, args, log)
        except GuardFailure as e:
            log(f"\n  [!!] [{e.invariant}] {e.detail}")
            return "failed", {"invariant": e.invariant}, \
                f"{e.invariant}：{e.detail.splitlines()[0]}"
        shot(state, frame, "located", log)
        data = {"mode": "only-locate", "program": prog.key,
                "screen_coords": list(sp),
                "offline": bool(args.adopt_frame)}
        data.update(info)
        note = locate_note(info) if locate_note else f"定位成功（{prog.display}）"
        return "ok", data, note

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
        ok, frame = click_and_confirm(state, frame, registry, args, log, prog,
                                      navigate=navigate, locate=locate,
                                      before_click=before_click)
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
                f"连续 {CLICK_RETRIES} 轮点击后画面无变化 —— "
                f"{prog.display} 很可能失焦静默挂起")

    # --- 8e --------------------------------------------------------------
    result, detail, frame_path = wait(state, registry, args, log, prog_log_window)
    # result -> 状态码的映射**只有一处**（finish()），zmd 与主流程共用，
    # 避免两条路径的映射表日后各自漂移。
    return finish(state, result, detail, frame_path, log)
