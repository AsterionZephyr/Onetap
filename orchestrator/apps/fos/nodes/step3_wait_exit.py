"""FOS 的节点 3：等它自己退出（**只读进程表**，不识别、不操作、不抓帧）。

为什么 FOS 的链条从 2 直接跳到 3、再跳到 9：它没有可编排的界面（见
`apps/fos/__init__.py` 的模块 docstring）。本节点只做一件事 —— 反复采样进程表，
直到**连续 CONFIRM_SAMPLES 次**看不见 MPA 目录下的进程，才认为这一轮结束。

## 三条刻意的选择

1. **dry-run 照常等**。别处的 dry-run 是「到点击为止」，而 FOS 的等待本身不是
   操作（只读进程表）；若在这里提前返回，节点 2 已经把 FOS 启动了 —— 于是它
   会带着还在跑的 FOS 去跑下一个程序，两边同时动鼠标/游戏。故本节点只在日志里
   说明一句，然后照常等。
2. **超时只回报 timeout**，由节点 9 按既有口径收尸（本节点不做任何 kill）。
3. **一次都没看见 => failed**，不是 completed。启动后 1 秒内就消失的程序不可能
   干过活；把它记成 completed 就是静默失效（用户会以为 FOS 跑过了）。
"""

from .... import frameops            # orchestrator/frameops.py（不在 steps 包里）
from ....steps import context
from ....statuses import COMPLETED, FAILED, TIMEOUT

from .. import (CONFIRM_SAMPLES, POLL_SECONDS, WAIT_TIMEOUT_SECONDS,
                describe, fos_processes, wait_exit)


def extra_args(ap):
    ap.add_argument("--wait-timeout", type=float, default=WAIT_TIMEOUT_SECONDS,
                    help="等 FOS 自行退出的上限（秒，默认 "
                         f"{WAIT_TIMEOUT_SECONDS:.0f}；也给够 --run-timeout）")
    ap.add_argument("--poll", type=float, default=POLL_SECONDS,
                    help=f"采样间隔（秒，默认 {POLL_SECONDS:.1f}）")


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)

    if args.dry_run:
        log("  [DRY RUN] FOS 没有可演练的动作（识别/点击都不存在）："
            "等待本身不是操作，照常等它退出")

    log(f"\n[等] {prog.display} 自行退出：上限 {args.wait_timeout:.0f}s，"
        f"轮询 {args.poll:.1f}s，连续 {CONFIRM_SAMPLES} 次为空才算结束")
    log(f"  采样起点进程：{describe(fos_processes())}")

    res = wait_exit(log, prog, timeout=args.wait_timeout, poll=args.poll)
    elapsed = res["elapsed"]

    if res["state"] == "exit":
        if not res["seen"]:
            return frameops.finish(
                state, FAILED,
                f"启动后 {elapsed:.0f}s 内一次都没观察到 FOS 进程 —— "
                f"多半启动即失败（无法确认它跑过）", None, log)
        return frameops.finish(
            state, COMPLETED,
            f"{prog.display} 已于 {elapsed:.0f}s 自行退出"
            f"（连续 {CONFIRM_SAMPLES} 次采样为空）", None, log)

    return frameops.finish(
        state, TIMEOUT,
        f"{prog.display} 在 {args.wait_timeout:.0f}s 内没有退出：还剩 "
        f"{describe(res['last'])}（由节点 9 决定怎么收）", None, log)


if __name__ == "__main__":
    raise SystemExit(context.run_step("3", "wait_exit", body, extra_args,
                                      chain_key="fos"))
