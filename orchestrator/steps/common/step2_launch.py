"""节点 2：启动目标程序的第一层（README §5 步骤 [1] 的前半）

只负责**把第一层进程拉起来**，不等窗口、不点击。
第一层会自行检查更新并启动第二层（`Scheduling auto-start for 'ok-ww' in 10 seconds`），
**全程无需点击**（T-4）。

幂等：已经在跑就不重复启动（`window.running(prog)` 按**可执行路径前缀**判定归属，
避免把本机无关的 pythonw.exe 误算进来）。

目标程序由 `state.json` / `--target` 决定（ok-ww 或 ok-nte），
两程序共用本节点 —— exe 路径、进程名都取自 `orchestrator.programs`。

单独跑：

    python -m orchestrator.steps.common.step2_launch --adopt-existing
    python -m orchestrator.steps.common.step2_launch --no-launch
    python -m orchestrator.steps.common.step2_launch --target nte

`--adopt-existing`：程序已经在跑，只记录、不启动。
`--no-launch`    ：假定已在运行，连检查都不做（供人工接管场景）。
"""

from ... import window
from ...errors import DiscoveryFailure

from .. import context


def extra_args(ap):
    ap.add_argument("--no-launch", action="store_true",
                    help="不启动，假定 ok-ww 已在运行")
    ap.add_argument("--adopt-existing", action="store_true",
                    help="若已在运行则只记录（默认行为也是幂等的，此参数仅作显式声明）")


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    if args.no_launch:
        log(f"  [跳过] --no-launch：假定 {prog.display} 已在运行")
        alive = window.running(prog)
        log(f"  当前 {prog.display} 相关进程：{[(n, p) for n, p, _ in alive]}")
        return "skipped", {"launched": False, "alive": len(alive)}, "按参数跳过启动"

    alive = window.running(prog)
    if alive:
        log(f"  已在运行，不重复启动：{[(n, p) for n, p, _ in alive]}")
        state.set("launched_by_us", False)
        return "ok", {"launched": False, "alive": len(alive)}, "已在运行"

    try:
        window.launch(prog, log=log)
    except DiscoveryFailure as e:
        log("")
        log(str(e))
        return "failed", {"launched": False}, "可执行文件缺失"

    state.set("launched_by_us", True)
    return "ok", {"launched": True}, f"已启动 {prog.exe}"


if __name__ == "__main__":
    raise SystemExit(context.run_step("2", "launch", body, extra_args))
