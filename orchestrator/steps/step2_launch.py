"""节点 2：启动 ok-ww.exe（README §5 步骤 [1] 的前半）

只负责**把第一层进程拉起来**，不等窗口、不点击。
第一层会自行检查更新并启动第二层（`Scheduling auto-start for 'ok-ww' in 10 seconds`），
**全程无需点击**（T-4）。

幂等：已经在跑就不重复启动（`okww_running()` 按可执行路径前缀判定归属，
避免把本机无关的 pythonw.exe 误算进来）。

单独跑：

    python -m orchestrator.steps.step2_launch --adopt-existing
    python -m orchestrator.steps.step2_launch --no-launch

`--adopt-existing`：程序已经在跑，只记录、不启动。
`--no-launch`    ：假定已在运行，连检查都不做（供人工接管场景）。
"""

from .. import window
from ..errors import DiscoveryFailure

from . import context


def extra_args(ap):
    ap.add_argument("--no-launch", action="store_true",
                    help="不启动，假定 ok-ww 已在运行")
    ap.add_argument("--adopt-existing", action="store_true",
                    help="若已在运行则只记录（默认行为也是幂等的，此参数仅作显式声明）")


def body(args, state, log):
    if args.no_launch:
        log("  [跳过] --no-launch：假定 ok-ww 已在运行")
        alive = window.okww_running()
        log(f"  当前 ok-ww 相关进程：{[(n, p) for n, p, _ in alive]}")
        return "skipped", {"launched": False, "alive": len(alive)}, "按参数跳过启动"

    alive = window.okww_running()
    if alive:
        log(f"  已在运行，不重复启动：{[(n, p) for n, p, _ in alive]}")
        state.set("launched_by_us", False)
        return "ok", {"launched": False, "alive": len(alive)}, "已在运行"

    try:
        window.launch_okww(log=log)
    except DiscoveryFailure as e:
        log("")
        log(str(e))
        return "failed", {"launched": False}, "可执行文件缺失"

    state.set("launched_by_us", True)
    return "ok", {"launched": True}, f"已启动 {window.OKWW_EXE}"


if __name__ == "__main__":
    raise SystemExit(context.run_step("2", "launch", body, extra_args))
