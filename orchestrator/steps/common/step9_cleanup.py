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

    python -m orchestrator.steps.common.step9_cleanup --survey      # 只看现状，不动手
    python -m orchestrator.steps.common.step9_cleanup --force       # 无论结果如何都清理
"""

import argparse
import time

from ... import cleanup as cleanup_mod
from ... import watchdog
from ... import window
from ...orchestrator import COMPLETED, FAILED, TIMEOUT, UNKNOWN

from .. import context

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
    # ⚠️ `--keep-game` 是**主控 main.py** 的参数，节点子进程默认收不到它。
    # 这里必须自己也声明一份，否则 `args.keep_game` 会 AttributeError
    # （实测：UNKNOWN + 游戏残留收尾分支一跑到就炸）。
    # 主控在拼命令行时若带了 --keep-game 会一并透传；不带则默认为 False，
    # 即「按用户裁定到点连游戏一起收尾」。
    ap.add_argument("--keep-game", action="store_true",
                    help="收尾时保留游戏进程（默认连游戏一起关）")


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

        # ⚠️ 游戏侧也要**确认**（不改 Q3「不杀」的决策，只是把状态说出来）。
        #
        # 为什么必须查：Q3 的前提是「程序退出时自己把游戏杀掉」。实测该前提
        # **只对游戏本体成立** —— ok-nte 会关 `HTGame.exe`，但**留下 launcher**
        # `NTEGame.exe`（实测 2026-10-16 两次跑完都留：pid=43684 与 pid=25736，
        # 带 8 个窗口含托盘图标）。上一版这里只看 `window.running(prog)`，
        # 于是「无残留进程」这句话**只覆盖目标程序自己**，游戏侧的残留
        # 完全没被提及 —— 属于「报了个让人以为一切干净的结论」。
        game = []
        try:
            game = watchdog.game_processes(prog)
        except Exception as e:                      # noqa: BLE001
            log(f"  [警告] 查游戏进程失败：{e}")
        if game:
            names = sorted({n for n, _p, _e in game})
            log(f"  [注意] 游戏侧仍有进程存活：{[(n, p) for n, p, _ in game]}")
            log(f"         {'/'.join(names)} —— {prog.display} 通常只关游戏本体，"
                f"launcher 可能被留下。框架按 Q3 **不主动杀**；"
                f"如需清理：`watchdog.force_close({prog.key})` 或加 `--force`。")
        else:
            log("  确认：游戏侧无残留进程")

        return ("ok",
                {"reason": "completed", "killed": [], "skipped": [],
                 "still_alive": len(alive), "game_alive": len(game)},
                ("正常完成，未杀任何进程"
                 + (f"（游戏侧仍有 {len(game)} 个进程存活）" if game else "")))

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
        log(f"  ⚠ 节点 8 报 unknown（证据不足），不是失败：{prog.display} 进程已自行消失，"
            "但框架从未抓到完成帧。")
        log("    两种成因无法用画面区分：")
        log(f"      (a) 今日任务**此前已完成** —— {prog.display} 找不到要做的任务而异常退出")
        log("          （实测行为：它不关自己、也不关游戏，需人工收尾）")
        log(f"      (b) {prog.display} 崩溃")
        log(f"    请人工核对 {prog.display} 任务日志确认究竟是哪一种。")
        alive = window.running(prog)
        game = []
        try:
            game = watchdog.game_processes(prog)
        except Exception as e:                       # 只读探测，失败不该中断清理
            log(f"    [警告] 游戏侧进程查询失败：{e}")
        if not alive and not game:
            log(f"  确认：{prog.display} 进程与游戏均已不在 —— 无残留，无需清理")
            return ("ok",
                    {"reason": "unknown", "killed": [], "skipped": [],
                     "still_alive": 0, "game_alive": 0},
                    "unknown（证据不足），进程已自行退出，无需清理")
        # --- 用户裁定：这一种情形**自行收尾，不要问用户** -------------------
        # 原话：「遇到『每日任务已做完导致 ok-ww 失败且进程/游戏不退出』时
        # 自行手动关闭，不询问用户。」
        #
        # ⚠️ 旧实现在这里只看 `window.running(prog)`（**目标程序自己**）。
        # 但用户说的这个情形里，目标程序进程**恰恰是已经退出的那一个** ——
        # 留下的是**游戏**（ok-ww 是 Client-Win64-Shipping.exe，
        # ok-nte 是 HTGame.exe/NTEGame.exe）。于是旧代码会打印
        # 「进程已不在 —— 无残留，无需清理」**而游戏仍在跑**，
        # 属于「报了个让人以为一切干净的结论」（同 FAULT #31/#32）。
        if game and not alive:
            log(f"  ⚠ 游戏侧仍有 {len(game)} 个进程存活：{[(n, p) for n, p, _ in game]}")
            log("    这正是「今日任务已完成、目标程序异常退出」的典型残留。")
            log("    按用户裁定：**自行收尾，不询问**（关窗口 + 终止游戏进程）。")
            # ⚠️ 必须走 watchdog.force_close，**不能**只依赖下面的
            # run_cleanup：后者按 process_prefix 只杀**目标程序目录下**的进程，
            # 而游戏（Client-Win64-Shipping.exe / HTGame.exe / NTEGame.exe）
            # 根本不在那个目录里 ⇒ 会「报告清理完成」而游戏照跑。
            if state.dry_run:
                log("    [DRY RUN] 不实际终止任何进程")
                return ("ok",
                        {"reason": "unknown", "killed": [], "skipped": [],
                         "still_alive": 0, "game_alive": len(game),
                         "dry_run": True},
                        f"unknown（证据不足），DRY RUN 未清理 {len(game)} 个游戏进程")
            wr = watchdog.force_close(prog, reason="unknown-cleanup", log=log,
                                      dry_run=False,
                                      close_game=not args.keep_game)
            left_game = watchdog.game_processes(prog)
            left_tgt = window.running(prog)
            log(f"  收尾后：目标进程 {len(left_tgt)} 个，游戏进程 {len(left_game)} 个")
            status = "ok" if not left_game and not left_tgt else "failed"
            # ⚠️ 措辞别用 killed_game 的条数当「清掉了几个」——
            # 实测 launcher 是收到 WM_CLOSE 后**自己体面退出**的，
            # killed_game 为空，但确实清干净了。写「终止游戏 0 个」会让人
            # 以为没生效（同 FAULT #13 的措辞教训）。改报**清掉的数量**。
            cleared = len(game) - len(left_game)
            return (status,
                    {"reason": "unknown-cleanup", "killed": wr.get("killed_game", []),
                     "skipped": [], "still_alive": [(n, p) for n, p, _ in left_tgt],
                     "game_alive": len(left_game),
                     "game_cleared": cleared},
                    (f"unknown（证据不足）；已按裁定自行收尾，"
                     f"游戏侧清掉 {cleared}/{len(game)} 个"
                     + (f"，仍有 {len(left_game)} 个存活" if left_game else "")))
        else:
            log(f"  仍有进程存活 目标={[(n, p) for n, p, _ in alive]}"
                f" 游戏={[(n, p) for n, p, _ in game]} —— 转常规清理路径")
        # 落到下面的常规清理路径

    # --- 超时 / 失败：走清理路径 -------------------------------------------
    reason = args.reason or result or "manual"
    log(f"  结果 = {result}（{state.get('result_detail', '')}）-> 走清理路径")
    if state.dry_run:
        log("  [DRY RUN] 不实际终止任何进程")

    res = cleanup_mod.run_cleanup(prog.root_dir, program=prog, reason=reason,
                                  log=log, dry_run=state.dry_run)
    log(f"  终止 {len(res['killed'])} 个，跳过 {len(res['skipped'])} 个")

    # ⚠️ dry-run **必须在这里返回**，不能落到下面那段「还有进程存活」判定：
    # 我们**根本没杀**，进程当然还在，于是那段会打印
    # 「已等待 5s 仍未退出 —— 这次确实可能是权限问题」并报 failed/退出码 3，
    # 让整条链在最后一节停手。实测 `main.py --target zmd --dry-run` 就是这样
    # 在节点 9 假失败（前 7 节全 OK）。dry-run 的语义是「只规划不执行」，
    # 它的结论也只能是「计划了什么」，而不是「清理是否成功」。
    if state.dry_run:
        still = window.running(prog)
        log(f"  [DRY RUN] 未终止任何进程（当前仍存活 {len(still)} 个，属预期）")
        return ("ok",
                {"reason": reason, "killed": [], "skipped": res["skipped"],
                 "still_alive": [(n, p) for n, p, _ in still], "dry_run": True},
                f"dry-run：计划终止 {len(res['skipped'])} 个，未实际执行")

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
