"""节点 8：任务循环（README §5 步骤 [4] [5] [6] [7]）

本节点把 README §5 的四步收在一份代码里，因为它们**共用一个闭环**：
导航 -> 定位 -> 点击 -> 验证 -> 等待完成。拆开反而会切断"点击落空就重试整轮"的逻辑。

内部按小阶段推进（每段都打印独立标题，便于定位出错位置）：

    8a  导航    若不在任务页，点侧栏图标过去；点击后**重新抓帧闭环验证**
    8b  定位    定位「每日任务」行 -> 扫描同行「开始」按钮 -> 交叉验证
    8c  点击    动作前置关（屏幕内 + 前台 + 目标顶层）-> 真实光标点击
    8d  验证    点击后帧差异 >= 阈值才算生效；否则**重试整轮**（N=3）
    8e  等待    轮询完成帧 / 计时器冻结，直到完成 / 超时 / 失败

终止行为三分（HANDOFF §6）——**必须区分**，因为随后的清理行为完全不同：

    完成  抓到完成帧，ok-ww 自行退出          -> 不杀任何进程
    超时  计时器冻结 180s（ok-ww 在等游戏）   -> 走清理路径
    失败  进程消失但从未抓到完成帧            -> 走清理路径

⚠️ 当前 `exit_notice` 资产**未采集**（见 assets.json），所以「完成帧」判不出来，
本节点只能以**超时**收场。程序会明确打印这个缺口，不会假装成功 ——
证据不足时报 UNKNOWN/TIMEOUT，**绝不默认成功**（INV-30）。

单独跑：

    python -m orchestrator.steps.step8_run_task --dry-run          # 只定位不点击
    python -m orchestrator.steps.step8_run_task                    # 真实点击 + 等待
    python -m orchestrator.steps.step8_run_task --only-locate      # 只跑 8a+8b
"""

import os
import time

from .. import assets as assets_mod
from .. import capture as capture_mod
from .. import input as input_mod, match, state as state_mod, win32, window
from ..errors import GuardFailure
from ..orchestrator import (
    CHANGE_THRESHOLD, CLICK_RETRIES, CLICK_RETRY_INTERVAL, COMPLETED, FAILED,
    FREEZE_SECONDS, NAV_RETRIES, POLL_INTERVAL, TIMEOUT, TOTAL_TIMEOUT,
)

from . import context


def extra_args(ap):
    ap.add_argument("--freeze-seconds", type=float, default=FREEZE_SECONDS,
                    help=f"计时器冻结多少秒后判超时（默认 {FREEZE_SECONDS:.0f}）")
    ap.add_argument("--total-timeout", type=float, default=TOTAL_TIMEOUT,
                    help=f"整条链兜底上限（秒），默认 {TOTAL_TIMEOUT:.0f}")
    ap.add_argument("--only-locate", action="store_true",
                    help="只跑 8a 导航 + 8b 定位，不点击、不等待")
    ap.add_argument("--adopt-frame", default=None,
                    help="用这张 PNG 代替首次抓帧（离线验证定位链）")
    ap.add_argument("--offline", action="store_true",
                    help="离线模式：不发现窗口、不点击，只用 --adopt-frame 验证定位链")


# ------------------------------------------------------------ 抓帧工具


def grab(state, strict=True, log=None):
    """抓一帧（每次都用**重新发现**的 hwnd，遵守 INV-14）。"""
    hwnd = context.require_hwnd(state, log=None)
    f = capture_mod.grab_frame(hwnd, strict_content=strict)
    state.set("hwnd", hwnd)
    return hwnd, f


def shot(state, frame, tag, log=None):
    from PIL import Image
    path = state.shot_path(tag)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(frame.rgb if hasattr(frame, "rgb") else frame).save(path)
    state.add_shot("8", path)
    if log:
        log(f"  [落盘] {os.path.relpath(path, state.run_dir)}")
    return path


# ------------------------------------------------------------ 8a 导航


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
            match.locate_daily_row(frame.rgb, row_tpl)
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
        sidebar = registry["sidebar_tasks"]
        tpl = sidebar.load()
        ident = match.verify_identity(frame.rgb, tpl)
        th, tw = tpl.shape[:2]
        cx = ident["pos"][0] + tw // 2
        cy = ident["pos"][1] + th // 2
        hwnd = state.get("hwnd")
        if not hwnd:
            raise GuardFailure("INV-23", "导航需要窗口句柄，但当前没有（离线模式请加 --only-locate）")
        sp = win32.client_to_screen(hwnd, cx, cy)
        if sp is None:
            raise GuardFailure("INV-23", "ClientToScreen 失败")
        log(f"  侧栏图标窗口内中心=({cx},{cy}) -> 屏幕 ({sp[0]},{sp[1]})")
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


# ------------------------------------------------------------ 8b 定位


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

    loc = match.locate_daily_row(frame.rgb, row_tpl)
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


# ------------------------------------------------- 8c/8d 点击 + 验证


def click_and_confirm(state, frame, registry, args, log):
    """点击「开始」并验证生效；无变化则**重试整轮**（Q8：N=3）。

    重试时重新置前台、重新定位、重新点击 —— 因为 ok-ww 会自己移动鼠标
    （MouseResetTask，日志 125 处 `move mouse back`），点击后若依赖光标位置需重新确认。
    """
    for attempt in range(1, CLICK_RETRIES + 1):
        log(f"\n[8c] 点击 第 {attempt}/{CLICK_RETRIES} 轮")
        frame, _ = navigate_to_tasks(state, frame, registry, args, log)
        sp, _y0, _y1, _loc = locate_and_click_start(state, frame, registry, log)
        shot(state, frame, "about-to-click", log)

        before = frame.rgb.astype("int16")
        input_mod.guarded_click(state.get("hwnd"), sp[0], sp[1],
                                dry_run=args.dry_run, log=log)
        if args.dry_run:
            return True, frame

        log("\n[8d] 验证已启动")
        time.sleep(1.2)
        _, after = grab(state, strict=False, log=log)
        diff = float(abs(after.rgb.astype("int16") - before).mean())
        log(f"  点击后帧差异 = {diff:.2f}（阈值 {CHANGE_THRESHOLD}）")
        if diff >= CHANGE_THRESHOLD:
            log("  [OK] 画面已变化，点击很可能生效")
            shot(state, after, "after-click", log)
            return True, after
        log("  [!!] 画面几乎未变 —— 点击可能落空（ok-ww 失焦会静默挂起）")
        shot(state, after, f"no-change-try{attempt}", log)
        if attempt < CLICK_RETRIES:
            log(f"  等待 {CLICK_RETRY_INTERVAL:.0f}s 后重试整轮")
            time.sleep(CLICK_RETRY_INTERVAL)

    return False, frame


# --------------------------------------------------------- 8e 等待完成


def wait_for_completion(state, registry, args, log):
    """等待完成 / 超时。返回 (result, detail, shot_path)。

    判据（Q7 决策）：**同一帧内 横幅 + 退出通知**。
    「横幅」用顶部条带亮度代理，「退出通知」用图像资产匹配 —— 不引入 OCR。
    宁可漏判（退回超时），不可误判 —— 误判会把一次卡死当成成功。
    """
    log(f"\n[8e] 等待完成：采样 {POLL_INTERVAL}s；"
        f"冻结判定 {args.freeze_seconds:.0f}s；兜底 {args.total_timeout:.0f}s")

    exit_tpl = None
    exit_asset = registry.get("exit_notice")
    if exit_asset and exit_asset.available:
        exit_tpl = exit_asset.load()
    else:
        log("  [警告] 退出通知资产未采集 —— 无法判定「正常完成」，"
            "本节点只能以「超时」收场")
        log("         这是当前**唯一的功能缺口**，采集方法见 assets.json")

    detector = state_mod.FreezeDetector(args.freeze_seconds)
    started = time.time()
    last_fp = None
    completion_seen = False
    last_report = 0.0

    while True:
        now = time.time()
        elapsed = now - started

        if elapsed > args.total_timeout:
            return TIMEOUT, f"整条链超过兜底上限 {args.total_timeout:.0f}s", None

        # ok-ww 进程没了 —— 分两种：抓到过完成帧 = 完成；没抓到 = 失败
        if not window.okww_running():
            if completion_seen:
                return COMPLETED, "ok-ww 已自行退出（此前抓到完成帧）", None
            return FAILED, "ok-ww 进程消失，但从未抓到完成帧", None

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


# ------------------------------------------------------------- 主流程


def body(args, state, log):
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

    # --- 8a + 8b（--only-locate 到此为止）---------------------------------
    if args.only_locate:
        try:
            f, _nav = navigate_to_tasks(state, f, registry, args, log)
            sp, y0, y1, loc = locate_and_click_start(state, f, registry, log)
        except GuardFailure as e:
            log(f"\n  [!!] [{e.invariant}] {e.detail}")
            return "failed", {"invariant": e.invariant}, \
                f"{e.invariant}：{e.detail.splitlines()[0]}"
        shot(state, f, "located", log)
        return ("ok",
                {"mode": "only-locate", "screen_coords": list(sp),
                 "row_y0": y0, "row_y1": y1,
                 "anchor_score": loc["anchor"]["score"],
                 "button_center": list(loc["button"]["center"]),
                 "offline": bool(args.adopt_frame)},
                f"定位成功 锚点 {loc['anchor']['score']:.4f} "
                f"按钮窗口内 {tuple(loc['button']['center'])}")

    # --- 8c + 8d ---------------------------------------------------------
    try:
        ok, f = click_and_confirm(state, f, registry, args, log)
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
    result, detail, frame_path = wait_for_completion(state, registry, args, log)
    log(f"\n[结果] {result}：{detail}")
    state.set("result", result)
    state.set("result_detail", detail)

    status = {"completed": "ok", "timeout": "timeout", "failed": "failed"}.get(
        result, "failed")
    return (status,
            {"result": result, "detail": detail, "completion_frame": frame_path},
            f"{result}：{detail}")


if __name__ == "__main__":
    raise SystemExit(context.run_step("8", "run_task", body, extra_args))
