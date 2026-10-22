"""节点 6：抓首帧并校验（程序无关的实现）

四条不变量在这里拦截（详见 orchestrator/capture.py）：

  INV-1   帧尺寸必须等于当次窗口 rect。不一致时**绝不用该帧算坐标**。
  INV-13  帧全黑即中止（PrintWindow 对 Qt 自绘返回全黑，故只用屏幕抓图）。
  INV-17  越界抓帧会**静默产出全黑帧**，故抓前先校验坐标在屏内。
  INV-22  置前台成功也可能落在最小化哨兵 rect (-32000)。
  另有 INV-12/INV-18：内容"健康"**不代表**抓到的是目标程序 —— 那是身份校验的职责。

⚠️ 本节点是「抓到别的窗口」这类事故的唯一闸门。开发中实际发生过两次：
帧尺寸、亮度、色彩数全都正常，但画面是**别的程序**。

## 程序差异走钩子（docs/adr/0005）

三件程序相关的事都以参数传进来，不在本文件里 if/else：

    identity(rgb, registry, log) -> {"score", "pos"}
        身份判据。ok-ww / ok-nte 用侧栏任务图标模板（本文件的 identity_check）；
        MaaEnd 用它自己底部那个绿色「开始任务」（apps/zmd/nodes/step6_first_frame.py）。
    pre_frame(state, args, log) -> None | (status, data, note)
        可选：抓帧前要处理的本程序专属闸门（MaaEnd 的「更新完成」弹窗）。
        它在 identity 之前 —— 弹窗遮罩正是压暗身份锚点的那个东西。
    identity_hint
        可选：身份校验超时时追加的一句程序专属提示。

FAULT #14（ok-ww 自带浮层遮住 ☰）：浮层实测是应用内绘制、非 Win32 子窗口，
编排点不掉、也枚举不到。处置（用户裁定）是**等它自行消失**，而不是弱化判据。
本节点因此会在一段时间内**反复重抓帧**，直到身份锚点出现或超时。
每次重抓都走完整的不变量链，**不降低任何严格性**。
超时上限默认 IDENTITY_TIMEOUT = 120 秒，可用 --identity-timeout 调整
（设 0 则只试一次）。

**离线调试**：--adopt-frame <png> 直接拿一张已落盘的帧跑校验链，完全不需要窗口。
这是本节点最常用的单跑姿势 —— 识别链的失败模式大多是静默的，
用历史帧反复喂才是可靠的验证方式。

单独跑（任何程序）：

    python -m orchestrator.steps.common.step6_first_frame --target ww --adopt-frame "probe/running-000.png"
"""

import os
import time

import numpy as np

from ... import assets as assets_mod
from ... import capture, input as input_mod, match
from ...errors import DiscoveryFailure, GuardFailure
from ...frameops import load_rgb

from .. import context

# FAULT #14：身份校验失败后的重试预算。启动浮层会遮住身份锚点，它是应用内绘制、
# 非 Win32 子窗口，编排无法关闭它，只能等它自行消失。用户裁定「等」而不是
# 「弱化判据」，故此预算给得宽（默认 2 分钟），且每次重试都重跑完整不变量链。
IDENTITY_TIMEOUT = 120.0
IDENTITY_INTERVAL = 3.0


def extra_args(ap):
    ap.add_argument("--adopt-frame", default=None,
                    help="不抓帧，直接用这张 PNG 跑校验链（离线调试用）")
    ap.add_argument("--no-strict-content", action="store_true",
                    help="不把「色彩可疑」当失败（诊断用）")
    ap.add_argument("--skip-identity", action="store_true",
                    help="跳过身份校验（**危险**，仅用于确认后续环节）")
    ap.add_argument("--identity-timeout", type=float, default=IDENTITY_TIMEOUT,
                    help=f"身份校验失败后重试的总时长（秒，默认 {IDENTITY_TIMEOUT:.0f}）。"
                         f"设为 0 则只试一次")
    ap.add_argument("--identity-interval", type=float, default=IDENTITY_INTERVAL,
                    help=f"重试间隔（秒，默认 {IDENTITY_INTERVAL:.1f}）")
    ap.add_argument("--no-foreground", action="store_true",
                    help="抓帧前不置前台（诊断用；会抓到遮挡窗口，见 FAULT #16）")
    ap.add_argument("--no-update-gate", action="store_true",
                    help="跳过本程序的抓帧前置闸门（诊断用）")


def identity_check(rgb, registry, log):
    """通用身份校验：确认这一帧确实来自目标程序（侧栏任务图标在场）。"""
    sidebar = registry["sidebar_tasks"]
    if not sidebar.available:
        raise DiscoveryFailure(
            f"身份校验所需的资产缺失：{sidebar.spec.get('file')}\n"
            f"  => 图像库报告：\n{registry.report()}")
    tpl = sidebar.load()
    ident = match.verify_identity(rgb, tpl)
    log(f"    [OK] score={ident['score']:.4f} pos={ident['pos']} "
        f"（INV-12：确认这帧真的来自目标程序）")
    return ident


def run(state, args, log, prog, identity, pre_frame=None, identity_hint=None):
    """抓首帧 + 不变量链 + 身份校验。identity 是本程序的身份判据（必填）。"""
    registry = assets_mod.Registry()
    log("\n[图像库]")
    log(registry.report())

    # --- 离线模式：拿一张已落盘的帧 --------------------------------
    if args.adopt_frame:
        src = os.path.abspath(args.adopt_frame)
        if not os.path.isfile(src):
            return "failed", {}, f"指定的帧不存在：{src}"
        rgb = load_rgb(src)
        h, w = rgb.shape[:2]
        log(f"\n  [离线] 采用 {src}  {w}x{h}")
        stats = {
            "mean_rgb": tuple(int(v) for v in rgb.reshape(-1, 3).mean(axis=0)),
            "distinct_colors_sampled": int(np.unique(
                (rgb.reshape(-1, 3)[::max(1, (w * h) // 4000)] >> 3).astype(np.int32)
            ).size),
        }
        mean_sum = sum(stats["mean_rgb"])
        log(f"  [校验] INV-13 均值RGB={stats['mean_rgb']} 色彩={stats['distinct_colors_sampled']}")
        if mean_sum < capture.MIN_MEAN_SUM:
            return "failed", stats, f"帧几乎全黑（均值 RGB {stats['mean_rgb']}）"

        dst = context.copy_into_run(state, src, "adopted-frame")
        state.add_shot("6", dst)
        state.set("frame", {"path": os.path.relpath(dst, state.run_dir).replace("\\", "/"),
                            "width": w, "height": h, "rect": None, "adopted": True})
        data = {"width": w, "height": h, "offline": True, "stats": stats}

        if args.skip_identity:
            log("  [跳过] 身份校验")
            return "ok", data, f"[离线] {w}x{h}（身份校验已跳过）"
        try:
            ident = identity(rgb, registry, log)
        except (GuardFailure, DiscoveryFailure) as e:
            log(f"    [!!] 身份校验失败：{e}")
            return "failed", {**data, "identity": None}, \
                f"身份校验失败（帧可能不是 {prog.display}）"
        data["identity"] = {"score": ident["score"], "pos": list(ident["pos"])}
        return "ok", data, f"[离线] {w}x{h} 身份 {ident['score']:.4f}"

    # --- 在线模式：真实抓帧 ----------------------------------------
    hwnd = context.require_hwnd(state, log=log)
    strict = not args.no_strict_content

    # ★ 本程序专属的抓帧前置闸门（如 MaaEnd 的「更新完成」模态框会压暗身份锚点）。
    # 双证据才点（应用日志 + 帧里 ack 形态），只有标记没有按钮 ⇒ 立即判
    # 「弹窗已不在」，不在骨架里空等。
    if pre_frame is not None and not args.no_update_gate:
        fail = pre_frame(state, args, log)
        if fail is not None:
            status, data, note = fail
            if isinstance(data, dict):
                data = {**data, "hwnd": hwnd}
            return status, data, note

    # FAULT #14：身份校验失败时**重试**（等浮层自行消失）。
    # 每次重试都重跑完整的不变量链 —— 不用「跳过校验」换取通过。
    deadline = time.time() + max(0.0, args.identity_timeout)
    attempt = 0

    while True:
        attempt += 1
        # hwnd 绝不缓存（INV-14）：每轮重新发现，窗口重建后也能跟上
        hwnd = context.require_hwnd(state, log=log) or hwnd

        # ⚠️ FAULT #16：**抓帧前必须置前台**（除诊断开关外）。
        # 屏幕抓图抓到的是「该矩形处屏幕上可见的东西」，不是「该 hwnd 的内容」。
        # 节点 6 在链里排在节点 7（置前台）**之前**，若自己不置前台，
        # 抓到的就是盖在目标程序上的任意窗口 —— 实测抓到过
        # 驱动终端、DSH 的 Electron 窗口、以及浏览器（近白帧 均值RGB (240,241,242)）。
        # 这些帧尺寸/亮度/色彩数**全部正常**，只有身份校验能拦住，
        # 于是表现为「身份校验随机失败、重试几次又好了」。
        if not args.no_foreground:
            try:
                input_mod.ensure_foreground(hwnd, log=None)
            except GuardFailure as e:
                log(f"  [警告] {e.invariant}：{e.detail.splitlines()[0]}")
                log(f"         仍继续抓帧 —— 若身份校验失败，多半就是这个原因")

        try:
            f = capture.grab_frame(hwnd, strict_content=strict)
        except GuardFailure as e:
            log(f"  [!!] [{e.invariant}] {e.detail}")
            if time.time() >= deadline:
                return "failed", {"hwnd": hwnd, "invariant": e.invariant}, \
                    f"{e.invariant}：{e.detail.splitlines()[0]}"
            log(f"  [重试] {args.identity_interval:.1f}s 后再抓一次"
                f"（第 {attempt} 次失败，剩余 {deadline - time.time():.0f}s）")
            time.sleep(args.identity_interval)
            continue

        log(f"  [OK] INV-1 帧 {f.width}x{f.height} == 窗口 rect")
        log(f"  [OK] INV-13 内容 均值RGB={f.stats['mean_rgb']} "
            f"色彩={f.stats['distinct_colors_sampled']}")

        # 落盘供肉眼复核（只靠数字会漏掉「抓到别的窗口」）
        from PIL import Image
        dst = state.shot_path("first-frame" if attempt == 1
                              else f"first-frame-attempt{attempt}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        Image.fromarray(f.rgb).save(dst)
        state.add_shot("6", dst)
        log(f"  [落盘] {os.path.relpath(dst, state.run_dir)}  ← **请肉眼复核**")

        state.set("frame", {"path": os.path.relpath(dst, state.run_dir).replace("\\", "/"),
                            "width": f.width, "height": f.height,
                            "rect": list(f.rect), "adopted": False})
        data = {"hwnd": hwnd, "width": f.width, "height": f.height,
                "rect": list(f.rect), "stats": f.stats, "offline": False,
                "attempts": attempt,
                "shot": os.path.relpath(dst, state.run_dir).replace("\\", "/")}

        if args.skip_identity:
            log("  [跳过] 身份校验")
            return "ok", data, f"{f.width}x{f.height}（身份校验已跳过）"

        log(f"  [身份校验] 第 {attempt} 次")
        try:
            ident = identity(f.rgb, registry, log)
        except (GuardFailure, DiscoveryFailure) as e:
            log(f"    [!!] 身份校验失败：{e}")
            if time.time() >= deadline:
                log(f"  [超时] 已重试 {attempt} 次、共 {args.identity_timeout:.0f}s，"
                    f"仍检不到 {prog.display} 的身份锚点")
                if identity_hint:
                    log(f"         {identity_hint}")
                else:
                    log("         （FAULT #14：很可能是应用内浮层一直挡着身份锚点，"
                        "该浮层非 Win32 子窗口，编排点不掉它）")
                return "failed", {**data, "identity": None}, \
                    f"身份校验失败（帧可能不是 {prog.display}，或界面被遮挡）"
            log(f"  [重试] {args.identity_interval:.1f}s 后再抓一次"
                f"（等浮层消失，剩余 {deadline - time.time():.0f}s）")
            time.sleep(args.identity_interval)
            continue

        data["identity"] = {"score": ident["score"], "pos": list(ident["pos"])}
        if attempt > 1:
            log(f"  [OK] 第 {attempt} 次尝试通过 —— 浮层已消失")
        return "ok", data, f"{f.width}x{f.height} 身份 {ident['score']:.4f}"


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    return run(state, args, log, prog, identity=identity_check)


if __name__ == "__main__":
    raise SystemExit(context.run_step("6", "first_frame", body, extra_args))
