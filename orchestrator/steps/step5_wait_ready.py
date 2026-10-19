"""节点 5：等待窗口就绪（README §5 步骤 [2a] 的前置）

**就绪 = 标题已是完整形态（含版本号）且 尺寸达到可用下限 且 连续采样稳定。**

⚠️ 为什么不能只看「rect 连续稳定」：第二层刚启动时窗口是 625x625 的一个**空壳**，
尺寸照样稳定，抓出来是纯色（实测 1 色），要靠 INV-13 才发现不对。
与其在抓帧阶段失败，不如把「可用」的条件前置到就绪判定里。

⚠️ 实测教训：窗口出现 ≠ 界面可用。ok-nte 在窗口出现后仍显示「正在启动, 120秒后超时.」
遮罩；ok-ww 启动后会**异步加载用户头像**，期间左上角像素随之改变。

单独跑：

    python -m orchestrator.steps.step5_wait_ready --timeout 300
"""

from .. import window
from ..errors import DiscoveryFailure

from . import context


def extra_args(ap):
    ap.add_argument("--timeout", type=float, default=window.READY_TIMEOUT,
                    help=f"等待上限（秒），默认 {window.READY_TIMEOUT:.0f}")
    ap.add_argument("--no-update-gate", action="store_true",
                    help="跳过目标程序的自我更新闸门（MaaEnd 专用；诊断用）")
    ap.add_argument("--update-wait", type=float, default=1800.0,
                    help="自我更新等待上限（秒，默认 1800；MaaEnd 实际 300MB 约 7 分钟）")


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)

    # ★ MaaEnd 自我更新：**先等它更新完**，再谈「窗口就绪」。
    # 解压替换发生在应用运行期间并随即重启进程，若正好落在下面的采样窗口里，
    # 本节点只会诚实但无用地说「窗口未就绪」。闸门只读日志、不点界面。
    # 放在 require_hwnd 之前：重启会换 hwnd（INV-14），等完再重新发现。
    if prog.key == "zmd" and not args.no_update_gate:
        from .. import apps as apps_mod
        upd = apps_mod.get("zmd").zmd_update_wait(
            state, log, max_wait=args.update_wait)
        if upd["state"] == "timeout":
            log(f"  [!!] 自我更新在 {args.update_wait:.0f}s 内没有收敛"
                f"（阶段 {upd['phase']}）")
            return "failed", {"update": upd}, \
                f"MaaEnd 自我更新未收敛（阶段 {upd['phase']}）"
        state.set("update_gate", upd)

    hwnd = context.require_hwnd(state, log=log)
    log(f"  等待就绪（最多 {args.timeout:.0f}s；"
        f"要求标题完整 + 尺寸 >= {prog.min_width}x{prog.min_height}"
        f" + 连续 {window.STABLE_SAMPLES} 次采样稳定）")
    try:
        st = window.wait_for_ready(hwnd, program=prog, log=log, timeout=args.timeout)
    except DiscoveryFailure as e:
        log("")
        log(str(e))
        return "failed", {"hwnd": hwnd}, "窗口未在超时内就绪"

    state.set("hwnd", hwnd)
    state.set("window_state", {k: st[k] for k in
                               ("left", "top", "width", "height")})
    log(f"  [OK] 就绪 {st['width']}x{st['height']} @ ({st['left']},{st['top']})")
    return ("ok",
            {"hwnd": hwnd, "width": st["width"], "height": st["height"],
             "left": st["left"], "top": st["top"]},
            f"就绪 {st['width']}x{st['height']}")


if __name__ == "__main__":
    raise SystemExit(context.run_step("5", "wait_ready", body, extra_args))
