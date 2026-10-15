"""节点 1：提权检查（README §5 流程的起点 · INV-7）

**硬前置**：非管理员直接中止。非提权会话杀不掉 ok-ww（实测 Stop-Process ->
Access denied），所以"先检查、再往下走"是唯一安全的顺序。

这一节**不碰任何程序**，只读本进程的令牌。故它可以随时单独重跑，没有副作用。

单独跑：

    python -m orchestrator.steps.step1_check_admin [--skip-admin-check]

诊断用途可加 `--skip-admin-check`：此时节点 9 **不会执行任何清理**。
"""

from .. import window
from ..errors import DiscoveryFailure

from . import context


def extra_args(ap):
    ap.add_argument("--skip-admin-check", action="store_true",
                    help="跳过提权自检（诊断用）。此时后续节点不会执行任何清理")


def body(args, state, log):
    if args.skip_admin_check:
        log("  [跳过] --skip-admin-check 已指定 —— 后续不会执行任何清理")
        state.set("skip_admin_check", True)
        return "skipped", {"is_admin": None, "skipped": True}, "按参数跳过"

    try:
        window.check_admin(log)
    except DiscoveryFailure as e:
        # 这一步的失败信息最有价值，原样打出来
        log("")
        log(str(e))
        state.set("skip_admin_check", False)
        return "failed", {"is_admin": False}, "未提权"

    state.set("skip_admin_check", False)
    return "ok", {"is_admin": True}, "已提权"


if __name__ == "__main__":
    raise SystemExit(context.run_step("1", "check_admin", body, extra_args))
