"""MaaEnd 的节点 8：整段交给 apps/zmd 的 zmd_run。

它**不套** steps/common/push.py 的骨架（这与另外两个程序不同，也是本程序
链条独立的理由之一）：MaaEnd 没有任务页、没有侧栏、任务页就是单页的任务 ID
列表，而且它跑完不退出 —— 完成只能读日志判。8b~8e 整段是自己的实现：

    zmd_locate / zmd_click_and_confirm / zmd_wait_completion / zmd_run

本节点只负责两件通用的事：取首帧（与骨架同一个 first_frame，支持
--adopt-frame 离线注入），以及把 GuardFailure 转成节点结果。

⚠️ 分派必须发生在 8a 之前：若落进 ok-ww 的定位链，第一步的侧栏图标匹配就会
失败 —— 而失败信息会指向「找不到侧栏」，与真正的问题（这个程序没有侧栏）
完全无关，把人引到错方向。
"""

from ....steps import context
from ....errors import GuardFailure
from ....steps.common import push

from .. import zmd_run


def extra_args(ap):
    push.extra_args(ap)


def body(args, state, log):
    frame, fail = push.first_frame(state, args, log)
    if fail is not None:
        return fail
    try:
        return zmd_run(state, args, frame, log)
    except GuardFailure as e:
        log(f"\n  [!!] [{e.invariant}] {e.detail}")
        return "failed", {"invariant": e.invariant}, \
            f"{e.invariant}：{e.detail.splitlines()[0]}"


if __name__ == "__main__":
    raise SystemExit(context.run_step("8", "run_task", body, extra_args,
                                      chain_key="zmd"))
