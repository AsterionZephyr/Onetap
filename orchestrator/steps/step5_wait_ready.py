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


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
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
