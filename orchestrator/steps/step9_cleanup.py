"""节点 9：退出与清理（README §5 步骤 [7] 的「兜底清理」）

用户裁定的清理策略（Q3 决策）——**四分，行为完全不同**：

    正常完成（completed）  ok-ww 自己退出，游戏也由它自己杀。
                          框架**不杀任何进程**，只**确认**。
    ============================================================
    未决（unknown）        ok-ww 进程已自行消失，但没抓到完成帧
                          （FAULT #17）。**也无需清理**，但要把
                          「无法判定成因」再讲一遍（INV-30）。
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
import time

from .. import cleanup as cleanup_mod
from .. import window
from ..orchestrator import COMPLETED, FAILED, TIMEOUT, UNKNOWN

from . import context

# 终止后等待进程从进程表消失的上限（FAULT #13）。
# 实测 kill 成功后立即枚举仍能读到同一 pid，故必须给有界等待，
# 否则误报 failed 并把人引去查「权限不足」（权限其实没问题）。
REAP_WAIT_SECONDS = 5.0


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
    prog = context.resolve_program(state, args, log=log)
    result = state.get("result")

    # --- 只读巡视 ---------------------------------------------------
    if args.survey or args.no_kill:
        log("  [只读] 列出将要终止的进程（不执行）")
        plan = cleanup_mod.plan_cleanup(prog.root_dir, program=prog, log=log)
        if not plan:
            log(f"  无 {prog.display} 目录下的残留进程")
        log(f"  合计 {len(plan)} 个将被终止")
        return ("ok",
                {"survey": True, "candidates": [
                    {"name": n, "pid": p, "exe": e} for n, p, e in plan]},
                f"巡视完毕，{len(plan)} 个候选")

    # --- 正常完成：不杀 --------------------------------------------------
    if result == COMPLETED and not args.force:
        log(f"  任务正常完成 —— {prog.display} 自行退出，框架**不杀任何进程**（Q3 决策）")
        alive = window.running(prog)
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

    # --- 未决（unknown）：进程已自行消失，但仍要点明成因 --------------------
    # FAULT #17：节点 8 报 unknown 时 ok-ww **已经自己退出了**，清理多半无事可做。
    # 这里不能默默走清理路径 —— 人看到 unknown 的第一反应是「我的日常到底跑没跑」，
    # 必须把「无法判定」这句话再讲一遍（INV-30）。
    if result == UNKNOWN and not args.force:
        log("  ⚠ 节点 8 报 unknown（证据不足），不是失败：ok-ww 进程已自行消失，"
            "但框架从未抓到完成帧。")
        log("    两种成因无法用画面区分：")
        log("      (a) 今日任务**此前已完成** —— ok-ww 找不到要做的任务而异常退出")
        log("          （实测行为：它不关自己、也不关游戏，需人工收尾）")
        log("      (b) ok-ww 崩溃")
        log("    请人工核对 ok-ww 任务日志确认究竟是哪一种。")
        alive = window.running(prog)
        if not alive:
            log("  确认：ok-ww 进程已不在 —— 无残留，无需清理")
            return ("ok",
                    {"reason": "unknown", "killed": [], "skipped": [],
                     "still_alive": 0},
                    "unknown（证据不足），进程已自行退出，无需清理")
        # 还有残留（例如游戏没被关掉）-> 落到下面的常规清理路径
        log(f"  但仍有进程存活 {[(n, p) for n, p, _ in alive]} —— 转常规清理路径")

    # --- 超时 / 失败：走清理路径 -------------------------------------------
    reason = args.reason or result or "manual"
    log(f"  结果 = {result}（{state.get('result_detail', '')}）-> 走清理路径")
    if state.dry_run:
        log("  [DRY RUN] 不实际终止任何进程")

    res = cleanup_mod.run_cleanup(prog.root_dir, program=prog, reason=reason,
                                  log=log, dry_run=state.dry_run)
    log(f"  终止 {len(res['killed'])} 个，跳过 {len(res['skipped'])} 个")

    # ⚠️ FAULT #13：终止后**不能立刻**枚举就下结论。
    # 进程被 kill 到从进程表消失有延迟，实测「已终止 1 个」之后紧接一次
    # window.running(prog) 仍能读到同一个 pid ⇒ 误报 failed「仍有 1 个存活
    # （权限不足？）」，把人引去查权限（其实权限没问题）。
    # 给一个有界等待，真退出就报 ok。
    still = []
    if res["killed"] and not state.dry_run:
        wait_deadline = time.time() + REAP_WAIT_SECONDS
        while True:
            still = window.running(prog)
            if not still:
                log(f"  [OK] 进程已在 {REAP_WAIT_SECONDS:.1f}s 内全部退出")
                break
            if time.time() >= wait_deadline:
                break
            time.sleep(0.2)
    else:
        still = window.running(prog)

    if still:
        log(f"  [!!] 仍有 {prog.display} 相关进程存活：{[(n, p) for n, p, _ in still]}")
        log(f"      已等待 {REAP_WAIT_SECONDS:.1f}s 仍未退出 —— 这次**确实**可能是权限或残留问题")

    status = "ok" if not still else "failed"
    data = {"reason": reason, "killed": res["killed"], "skipped": res["skipped"],
            "still_alive": [(n, p) for n, p, _ in still]}
    # 措辞修正（FAULT #13）：等过 REAP_WAIT_SECONDS 还说活着，就不该再猜
    # 「权限不足？」—— 那会把排查引偏。如实报告「已等待仍未退出」。
    note = (f"已终止 {len(res['killed'])} 个"
            + (f"，等待 {REAP_WAIT_SECONDS:.0f}s 后仍有 {len(still)} 个存活"
               if still else ""))
    return status, data, note


if __name__ == "__main__":
    raise SystemExit(context.run_step("9", "cleanup", body, extra_args))
