"""ok-ww 的节点 8：只有三件事是它自己的。

8a 导航 -> 8b 定位 -> 8e 等待完成。点击重试、画面变化判据、日志窗口武装、
finish() 收尾都在 steps/common/push.py 的骨架里（docs/adr/0005）。

ok-ww 的任务页是**单行**「每日任务」+ 行内扫描最右亮像素 = 开始按钮。
"""

from ....steps import context
from ....steps.common import push

from .. import locate_and_click_start, navigate_to_tasks, wait_for_completion


def extra_args(ap):
    # ok-ww 的 8e 不消费 --stall-grace，用骨架默认值即可
    push.extra_args(ap)


# --- 骨架要的三件事 ------------------------------------------------------

def navigate(state, frame, registry, args, log):
    """8a：不在任务页就点侧栏图标过去（点完自己重新抓帧闭环）。"""
    frame, _loc = navigate_to_tasks(state, frame, registry, args, log)
    return frame


def locate(state, frame, registry, args, log):
    """8b：定位「每日任务」行 + 同行最右的「开始」按钮。"""
    sp, y0, y1, loc = locate_and_click_start(state, frame, registry, log)
    return sp, {"row_y0": y0, "row_y1": y1,
                "anchor_score": loc["anchor"]["score"],
                "button_center": list(loc["button"]["center"])}


def wait(state, registry, args, log, window_log):
    """8e：日志判据（终止标记），超时才落盘取证帧。"""
    return wait_for_completion(state, registry, args, log, window_log=window_log)


def locate_note(info):
    return (f"定位成功 锚点 {info['anchor_score']:.4f} "
            f"按钮窗口内 {tuple(info['button_center'])}")


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    return push.run(state, args, log, prog, navigate=navigate, locate=locate,
                    wait=wait, locate_note=locate_note)


if __name__ == "__main__":
    raise SystemExit(context.run_step("8", "run_task", body, extra_args,
                                      chain_key="ww"))
