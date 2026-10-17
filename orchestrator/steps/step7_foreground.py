"""节点 7：置前台 + 可用性校验（README §5 步骤 [2]）

真实光标点击有三个硬性后果，本节点是第一道闸门：

  INV-8   窗口必须在前台。**失焦时目标程序的 sleep() 没有出口，会静默挂起** ——
          症状是「点了毫无反应，且没有任何报错」。
  INV-22  置前台「成功」也可能是最小化哨兵 rect，故必须校验 rect。
  INV-23  「在前台」还不够：目标坐标处**最顶层**的窗口必须是目标程序。
          （INV-23 在节点 8 点击前由 input.guarded_click 再查一次。）

⚠️ 实测教训（INV-42）：**紧接上一个程序退出后启动下一个程序时，置前台会失败**
（实测 ok-nte 4 次尝试全败），而单独启动同一程序时第 1 次就成功。
成因是前台锁短暂拒绝焦点切换。⇒ 若本节点失败，先等 10 秒再重跑，不要急着改代码。

单独跑：

    python -m orchestrator.steps.step7_foreground
    python -m orchestrator.steps.step7_foreground --tries 20
"""

from .. import input as input_mod
from .. import window
from ..errors import GuardFailure

from . import context


def extra_args(ap):
    ap.add_argument("--tries", type=int, default=input_mod.FOREGROUND_TRIES,
                    help=f"抢前台尝试次数，默认 {input_mod.FOREGROUND_TRIES}")
    ap.add_argument("--just-focus", action="store_true",
                    help="只调用 SetForegroundWindow，不做可用性校验（诊断用）")


def body(args, state, log):
    hwnd = context.require_hwnd(state, log=log)

    if args.just_focus:
        ok = window.win32.set_foreground(hwnd)
        log(f"  [诊断] SetForegroundWindow -> {ok}（返回值不代表窗口可用）")
        return "skipped", {"hwnd": hwnd, "just_focus": True}, "仅诊断"

    try:
        st = input_mod.ensure_foreground(hwnd, tries=args.tries, log=log)
    except GuardFailure as e:
        log("")
        log(str(e))
        log("  => 提示：目标间的前台锁（INV-42）会让这一步失败。"
            "先等 10 秒再重跑本命令，通常第 1 次就成功。")
        return "failed", {"hwnd": hwnd}, f"{e.invariant}：置前台失败"

    log(f"  [OK] 前台 + 可用  {st['width']}x{st['height']} "
        f"@{st['left']},{st['top']}")
    state.set("hwnd", hwnd)
    state.set("foreground", True)
    return ("ok",
            {"hwnd": hwnd, "width": st["width"], "height": st["height"],
             "left": st["left"], "top": st["top"]},
            "已置前台且校验通过")


if __name__ == "__main__":
    raise SystemExit(context.run_step("7", "foreground", body, extra_args))
