"""节点 9：退出与清理（README §5 步骤 [7] 的「兜底清理」）

用户裁定的清理策略（Q3 决策）——**三分，行为完全不同**：

    正常完成（completed）  ok-ww 自己退出，游戏也由它自己杀。
                          框架**不杀任何进程**，只**确认**。
    ============================================================
    超时（timeout）/ 失败   走清理路径。

⚠️ 杀之前**必须确认该 pid 的可执行路径在 ok-ww 目录下**。
这是硬要求：本机同时有**无关的 python 进程**（如 searxng 的
`C:\\Python314\\python.exe`），而 ok-ww 的窗口持有者恰好也叫 `pythonw.exe`。
按进程名扫会误杀 —— `cleanup.plan_cleanup` 用路径前缀过滤掉它们。

本节点是**幂等**的：重复跑只会在没有残留时报"无残留"。

单独跑：

    python -m orchestrator.steps.step9_cleanup --survey      # 只看现状，不动手
    python -m orchestrator.steps.step9_cleanup --force       # 无论结果如何都清理
"""

import argparse

from .. import cleanup as cleanup_mod
from .. import window
from ..orchestrator import COMPLETED, FAILED, TIMEOUT

from . import context


def extra_args(ap):
    ap.add_argument("--survey", action="store_true",
                    help="只列出将要终止的进程，不执行（只读）")
    ap.add_argument("--force", action="store_true",
                    help="忽略 state.json 的结果，强制走清理路径")
    ap.add_argument("--reason", default=None,
                    help="清理原因标签（默认取 state.json 的 result）")
    ap.add_argument("--no-kill", action="store_true",
                    help="只规划不终止（等价于 --survey，语义更明确）")


def body(args, state, log):
    result = state.get("result")

    # --- 只读巡视 ---------------------------------------------------
    if args.survey or args.no_kill:
        log("  [只读] 列出将要终止的进程（不执行）")
        plan = cleanup_mod.plan_cleanup(window.OKWW_DIR, log=log)
        if not plan:
            log("  无 ok-ww 目录下的残留进程")
        log(f"  合计 {len(plan)} 个将被终止")
        return ("ok",
                {"survey": True, "candidates": [
                    {"name": n, "pid": p, "exe": e} for n, p, e in plan]},
                f"巡视完毕，{len(plan)} 个候选")

    # --- 正常完成：不杀 --------------------------------------------------
    if result == COMPLETED and not args.force:
        log("  任务正常完成 —— ok-ww 自行退出，框架**不杀任何进程**（Q3 决策）")
        alive = window.okww_running()
        if alive:
            log(f"  确认：仍有进程存活 {[(n, p) for n, p, _ in alive]}"
                f" —— 可能仍在收尾，稍后再看")
        else:
            log("  确认：无残留进程")
        return ("ok",
                {"reason": "completed", "killed": [], "skipped": [],
                 "still_alive": len(alive)},
                "正常完成，未杀任何进程")

    # --- 未提权：无力终止 -------------------------------------------------
    if state.get("skip_admin_check"):
        log("  [跳过] 未提权，框架无力终止进程 —— 请手动处理")
        return ("skipped",
                {"reason": "no-permission", "killed": [], "skipped": []},
                "未提权，跳过清理")

    # --- 超时 / 失败：走清理路径 -------------------------------------------
    reason = args.reason or result or "manual"
    log(f"  结果 = {result}（{state.get('result_detail', '')}）-> 走清理路径")
    if state.dry_run:
        log("  [DRY RUN] 不实际终止任何进程")

    res = cleanup_mod.run_cleanup(window.OKWW_DIR, reason=reason,
                                  log=log, dry_run=state.dry_run)
    log(f"  终止 {len(res['killed'])} 个，跳过 {len(res['skipped'])} 个")

    still = window.okww_running()
    if still:
        log(f"  [!!] 仍有 ok-ww 相关进程存活：{[(n, p) for n, p, _ in still]}")

    status = "ok" if not still else "failed"
    data = {"reason": reason, "killed": res["killed"], "skipped": res["skipped"],
            "still_alive": [(n, p) for n, p, _ in still]}
    note = (f"已终止 {len(res['killed'])} 个"
            + (f"，仍有 {len(still)} 个存活（权限不足？）" if still else ""))
    return status, data, note


if __name__ == "__main__":
    raise SystemExit(context.run_step("9", "cleanup", body, extra_args))
