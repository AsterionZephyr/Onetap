"""节点 4：等待第二层窗口（README §5 步骤 [1] 的后半）

ok-ww 是两层：第一层 `ok-ww.exe`（Tauri 外壳）拉起第二层 `pythonw.exe`（Qt 窗口），
**真正干活的是第二层**。第一层随后自行退出（`Kill Launcher After Start`），这是设计如此，
不是故障。

实测时间线（全程零点击）：pythonw 21.5s -> Qt 窗口 25.2s -> ok-ww.exe 约 27s 消失。

⚠️ 两个踩过的坑：

  1. **不能只按标题子串找**：第一层（class `Tauri Window`, 标题 `ok-ww`）与第二层
     （class `Qt...`, 标题 `OK-WW v3.6.7 China  - OK-WW`）都会被匹配到。取错第一层
     会让身份校验掉到 0.42。
  2. **超时要给足**：首次启动会停在应用更新页，窗口进入就绪可能更久。给 300s。

单独跑（程序已经在跑时最有用）：

    python -m orchestrator.steps.common.step4_wait_second_layer --timeout 300
    python -m orchestrator.steps.common.step4_wait_second_layer --adopt-hwnd 8196624
"""

import os

from ... import window
from ...errors import DiscoveryFailure

from .. import context


def extra_args(ap):
    ap.add_argument("--timeout", type=float, default=window.SECOND_LAYER_TIMEOUT,
                    help=f"等待上限（秒），默认 {window.SECOND_LAYER_TIMEOUT:.0f}")
    ap.add_argument("--adopt-hwnd", type=int, default=None,
                    help="跳过等待，直接用这个 hwnd（手工接管时用）")


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    if args.adopt_hwnd:
        info = window.win32.window_state(args.adopt_hwnd)
        if info is None:
            return "failed", {"hwnd": args.adopt_hwnd}, "指定的 hwnd 不存在"
        state.set("hwnd", args.adopt_hwnd)
        state.set("pid", window.win32.get_window_pid(args.adopt_hwnd))
        log(f"  [注入] 采用指定 hwnd={args.adopt_hwnd} "
            f"{info['width']}x{info['height']}")
        return "ok", {"hwnd": args.adopt_hwnd, "adopted": True}, "手工指定 hwnd"

    # ⚠️ 措辞按程序区分：MaaEnd 是**单层**（MaaEnd.exe 自己持窗口，
    # 没有第二层），把「等待第二层 Qt 窗口」这句话用在一个 Tauri 单层程序上，
    # 出问题时会把人引去找一个**不存在**的第二层。
    what = "第二层 Qt 窗口" if prog.has_second_layer else "窗口"
    log(f"  等待 {prog.display} {what}（最多 {args.timeout:.0f}s）")
    if prog.has_second_layer:
        log(f"  {prog.display} 第一层会自行放行；本框架**不点击任何东西**")
    else:
        log(f"  {prog.display} 是单层程序（{os.path.basename(prog.exe)} 自己持窗口）")
    try:
        info = window.wait_for_second_layer(prog, timeout=args.timeout, log=log)
    except DiscoveryFailure as e:
        log("")
        log(str(e))
        alive = window.running(prog)
        if not alive:
            return ("failed", {"hwnd": None},
                    f"没有 {prog.display} 进程在跑 —— {what}不可能出现")
        return "failed", {"hwnd": None}, f"{what}未在超时内出现"

    state.set("hwnd", info["hwnd"])
    state.set("pid", info["pid"])
    log(f"  hwnd={info['hwnd']} pid={info['pid']} class={info['class']}")
    log(f"  标题=[{info['title']}]")
    return ("ok",
            {"hwnd": info["hwnd"], "pid": info["pid"], "class": info["class"],
             "title": info["title"]},
            f"{what}就绪 hwnd={info['hwnd']}")


if __name__ == "__main__":
    raise SystemExit(context.run_step("4", "wait_second_layer", body, extra_args))
