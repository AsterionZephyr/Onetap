"""MaaEnd 的节点 5：等自我更新收敛，**再**谈窗口就绪。

为什么 MaaEnd 需要这道闸门、另外两个程序不需要：
它的自我更新是**运行期**做的 —— 解压替换完会重启进程。若那次重启正好落在
就绪判定的采样窗口里，骨架只会诚实但无用地说「窗口未在超时内就绪」，而真正
的原因（还在更新）完全不可见。这份等待只读应用日志，不点界面。

闸门放在 require_hwnd **之前**（骨架已保证）：重启会换 hwnd（INV-14），
等完再重新发现。
"""

from ....steps.common import step5_wait_ready as common
from ....steps import context

from .. import ZMD_UPDATE_WAIT_SECONDS, zmd_update_wait


def extra_args(ap):
    common.extra_args(ap)
    ap.add_argument("--no-update-gate", action="store_true",
                    help="跳过自我更新闸门（诊断用）")
    ap.add_argument("--update-wait", type=float, default=ZMD_UPDATE_WAIT_SECONDS,
                    help="自我更新等待上限（秒，默认 "
                         f"{ZMD_UPDATE_WAIT_SECONDS:.0f}；实测 300MB 约 7 分钟）")


def pre_ready(state, args, log):
    """等自我更新收敛；没收敛就整条链停在这里（不进入就绪判定）。"""
    if args.no_update_gate:
        return None
    upd = zmd_update_wait(state, log, max_wait=args.update_wait)
    if upd["state"] == "timeout":
        log(f"  [!!] 自我更新在 {args.update_wait:.0f}s 内没有收敛"
            f"（阶段 {upd['phase']}）")
        return "failed", {"update": upd}, \
            f"MaaEnd 自我更新未收敛（阶段 {upd['phase']}）"
    state.set("update_gate", upd)
    return None


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    return common.run(state, args, log, prog, pre_ready=pre_ready)


if __name__ == "__main__":
    raise SystemExit(context.run_step("5", "wait_ready", body, extra_args,
                                      chain_key="zmd"))
