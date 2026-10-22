"""ok-nte 的节点 8：只有三件事（加一个点击前置）是它自己的。

8a 导航 -> 8b 定位 -> 8c 前等游戏窗口稳定 -> 8e 逐项判完成。点击重试、
画面变化判据、日志窗口武装、finish() 收尾都在 steps/common/push.py 的骨架里。

ok-nte 的任务页是**多行复选列表** + 右下角唯一「开始」按钮（FAULT #22：
两个程序的任务页不同构，定位链不能共用）。
"""

from ....steps import context
from ....steps.common import push

from .. import (
    NTE_STALL_GRACE_SECONDS,
    nte_locate_start_button,
    nte_navigate_to_daily,
    nte_wait_game_settled,
    wait_for_nte_completion,
)


def extra_args(ap):
    # NTE_STALL_GRACE_SECONDS 是实测值（90s），由本程序自己给默认值
    push.extra_args(ap, stall_grace=NTE_STALL_GRACE_SECONDS)


# --- 骨架要的三件事 + 一个点击前置 --------------------------------------

def navigate(state, frame, registry, args, log):
    """8a：切到「每日」页（ok-nte 的侧栏与 ok-ww 不同构）。"""
    frame, _nav = nte_navigate_to_daily(state, frame, args, log)
    return frame


def locate(state, frame, registry, args, log):
    """8b：勾选复选列表 + 定位右下角唯一的「开始」按钮。"""
    sp, loc = nte_locate_start_button(state, frame, log, offline=args.offline)
    return sp, {"n_checked": loc["n_checked"],
                "boxes": [round(b["cy"], 1) for b in loc["boxes"]],
                "button_center": list(loc["button"]["center"])}


def before_click(state, args, log, attempt):
    """8c 前置：第 1 轮且非离线/演练时，等游戏窗口稳定。

    实测 ok-nte 点「开始」后会拉起游戏，若在游戏窗口尚在建立时重试整轮，
    会点进游戏画面。故只等一次（attempt == 1），重试轮不再等。
    """
    if attempt == 1 and not (args.offline or args.dry_run):
        nte_wait_game_settled(state, log)


def wait(state, registry, args, log, window_log):
    """8e：终止标记 + 逐项 success/failed/skipped 汇总。"""
    return wait_for_nte_completion(state, args, log, window_log=window_log)


def locate_note(info):
    return (f"定位成功（ok-nte）已勾选 {info['n_checked']} 项 "
            f"按钮窗口内 {tuple(info['button_center'])}")


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    return push.run(state, args, log, prog, navigate=navigate, locate=locate,
                    wait=wait, before_click=before_click,
                    locate_note=locate_note)


if __name__ == "__main__":
    raise SystemExit(context.run_step("8", "run_task", body, extra_args,
                                      chain_key="nte"))
