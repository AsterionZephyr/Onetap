"""steps.main — 主控：以**最简单的方式**按顺序启动各节点的脚本

设计取向：**主控不含任何业务逻辑**。它只做三件事：

    1. 建一个运行目录（state.json 就在里面）
    2. 用 `subprocess` 依次调用 `python -m orchestrator.steps.stepN_xxx`
    3. 看退出码决定是否继续

**为什么用子进程而不是 import**：子进程才能真正做到"断点"——
每个节点是独立进程，崩了不影响主控；命令行与手工单跑**完全一致**，
所以"主控跑到第 6 节失败"和"你手工跑第 6 节"是同一条路径、同一份日志、
同一份 state.json。改动隔离才成立。

退出码约定（与各 step 一致）：

    0  OK        -> 继续下一节
    3  校验失败   -> 停手（不变量被破坏 / 超时 / 失败）
    2  异常/环境  -> 停手

`--keep-going` 可以让它在某节失败后继续跑后面的（调试用，通常没意义）。

用法：

    python -m orchestrator.steps.main --dry-run         # 只校验与定位
    python -m orchestrator.steps.main                   # 完整执行
    python -m orchestrator.steps.main --from 6          # 从节点 6 接着跑
    python -m orchestrator.steps.main --only 8          # 只跑节点 8
    python -m orchestrator.steps.main --list            # 只列链条
"""

import argparse
import os
import subprocess
import sys
import time

from .. import programs
from .. import targets
from .. import watchdog
from .. import window
from . import context

HERE = os.path.dirname(os.path.abspath(__file__))

# 整轮运行的**墙钟**上限（秒）。用户裁定：半小时。
# 与 step8 的 --total-timeout 不同：这个从**开跑**算起，覆盖全部 8 个节点，
# 到点由 watchdog 关闭目标程序窗口 + 游戏窗口（必要时杀进程）。
# 见 watchdog 模块 docstring 关于「为什么 step 内部超时不够」的说明。
RUN_TIMEOUT = 1800.0

# 链条定义：节点号 -> (模块名, 中文名, 一句说明)
CHAIN = [
    ("1", "step1_check_admin", "提权检查", "非管理员直接中止（INV-7）"),
    ("2", "step2_launch", "启动目标程序", "拉起第一层，它自行启动第二层"),
    ("4", "step4_wait_second_layer", "等待窗口出现",
     "窗口持有者出现（ww/nte=第二层 Qt；zmd=单层 Tauri）"),
    ("5", "step5_wait_ready", "等待窗口就绪", "标题完整 + 尺寸达标 + 采样稳定"),
    ("6", "step6_first_frame", "抓首帧并校验", "INV-1/13/17/22 + 身份校验"),
    ("7", "step7_foreground", "置前台", "INV-8/22/23 的前置关"),
    ("8", "step8_run_task", "任务循环", "导航->定位->点击->验证->等待完成"),
    ("9", "step9_cleanup", "退出与清理", "正常完成不杀；超时/失败才杀"),
]

STEP_IDS = [c[0] for c in CHAIN]

# 每节可透传给 step 脚本的额外参数：(主控参数名, 目标节点, 传给 step 的旗标)
# 主控自己**不解释**这些参数，只做转发；None 表示内容为空时不转发。
PASSTHROUGH = [
    ("skip_admin_check", "1", "--skip-admin-check", False),
    ("no_launch", "2", "--no-launch", False),
    ("only_locate", "8", "--only-locate", False),
    ("total_timeout", "8", "--total-timeout", True),
    ("freeze_seconds", "8", "--freeze-seconds", True),
    # FAULT #30 的 STALLED 分支默认要等 90s 才判死；转发出去是为了让
    # 验证/SELFTEST 能把它调小，不必真等一分半。
    ("stall_grace", "8", "--stall-grace", True),
    ("force_clean", "9", "--force", False),
]


def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m orchestrator.steps.main",
        description="断点式编排主控：按 README §5 的顺序启动各节点脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="只做校验与定位，不点击、不等待、不清理")
    p.add_argument("--run-dir", default=None,
                   help="运行目录。省略时新建一个（除非 --resume）")
    p.add_argument("--resume", action="store_true",
                   help="沿用手工 --run-dir 或最近一次的运行目录")
    p.add_argument("--from", dest="from_step", default=None, metavar="N",
                   help=f"从节点 N 开始（{','.join(STEP_IDS)}）")
    p.add_argument("--to", dest="to_step", default=None, metavar="N",
                   help="跑到节点 N 为止（含）")
    p.add_argument("--only", default=None, metavar="N",
                   help="只跑节点 N")
    p.add_argument("--keep-going", action="store_true",
                   help="某节失败后仍继续（调试用）")
    p.add_argument("--pre-clean", action="store_true",
                   help="开始前先跑一次 step9 --force --survey 之外的强制清理")
    p.add_argument("--list", action="store_true",
                   help="只打印链条，不执行")
    p.add_argument("--python", default=sys.executable,
                   help="用来跑各节点的解释器（默认当前解释器）")
    p.add_argument("--step-arg", action="append", default=[], metavar="ARG",
                   help="原样透传给**每一个** step 的额外参数，可重复")
    p.add_argument("--show-cmd", action="store_true",
                   help="打印每节的完整命令行（便于手工复现）")
    # --- 目标程序 ---------------------------------------------------------
    # ⚠️ 默认 **None**（不是 "ww"）：省略时跟随 state.json 里的记录，
    # 这样 `--resume` 续跑不会把 ok-nte 的运行悄悄改回 ok-ww。
    # 取值由 orchestrator/targets.py 解析，**不写死在这里**：
    #   单个（ww / nte）      -> 跑一遍（老行为，运行目录就是 --run-dir）
    #   多个（ww,nte / all）  -> 逐个各跑一遍完整链条，各占一个子目录
    #   `both` 是历史写法，等价于 `all`。
    p.add_argument("--target", default=None, metavar="LIST",
                   help="目标程序：ww=ok-ww / nte=ok-nte / "
                        "ww,nte（逗号分隔，任意多个、按书写顺序） / all。"
                        "多个时**逐个各跑一轮完整链条**，各占一个子目录。"
                        "开跑时写入 state.json，全链共享")

    # --- 透传给特定节点的参数（见 PASSTHROUGH）-----------------------------
    # 这些参数只在它们所属的节点上生效，主控自己不做处理，只是转发。
    g = p.add_argument_group("透传给特定节点的参数")
    g.add_argument("--skip-admin-check", action="store_true",
                   help="[节点 1] 跳过提权自检（诊断用；此后不会执行任何清理）")
    g.add_argument("--no-launch", action="store_true",
                   help="[节点 2] 不启动 ok-ww，假定已在运行")
    g.add_argument("--only-locate", action="store_true",
                   help="[节点 8] 只跑导航 + 定位，不点击、不等待")
    g.add_argument("--freeze-seconds", type=float, default=None,
                   help="[节点 8] 计时器冻结多少秒后判超时")
    g.add_argument("--total-timeout", type=float, default=None,
                   help="[节点 8] 整条链兜底上限（秒）")
    g.add_argument("--stall-grace", type=float, default=None,
                   help="[节点 8] 执行器暂停后给它多少秒自行恢复；"
                        "仍无进展才判 STALLED（默认 90）")
    g.add_argument("--force-clean", action="store_true",
                   help="[节点 9] 忽略结果，强制走清理路径")

    # --- 整轮墙钟上限（用户裁定：半小时）---------------------------------
    g2 = p.add_argument_group("整轮时间上限")
    g2.add_argument("--run-timeout", type=float, default=RUN_TIMEOUT,
                    help=f"整轮运行的墙钟上限（秒），默认 {RUN_TIMEOUT:.0f}"
                         "（半小时）。到点由 watchdog 关闭目标程序窗口与游戏"
                         "窗口，必要时杀进程。设 0 则不限制")
    g2.add_argument("--keep-game", action="store_true",
                    help="超时收尾时**保留**游戏，只关目标程序"
                         "（默认按用户裁定：窗口和游戏都关）")
    g2.add_argument("--no-watchdog", action="store_true",
                    help="完全停用超时收尾（诊断用；挂住时要自己收拾现场）")
    return p


def selected_steps(args):
    """按 --only / --from / --to 算出要跑的节点序列。"""
    if args.only:
        ids = [str(args.only)]
        if ids[0] not in STEP_IDS:
            raise SystemExit(f"--only {args.only} 不在链条中：{STEP_IDS}")
        return ids

    ids = list(STEP_IDS)
    if args.from_step:
        if args.from_step not in STEP_IDS:
            raise SystemExit(f"--from {args.from_step} 不在链条中：{STEP_IDS}")
        ids = ids[ids.index(args.from_step):]
    if args.to_step:
        if args.to_step not in STEP_IDS:
            raise SystemExit(f"--to {args.to_step} 不在链条中：{STEP_IDS}")
        ids = ids[:ids.index(args.to_step) + 1]
    return ids


def step_specific_args(args, step_id):
    """把主控上与该节点相关的参数转成命令行参数。

    只转发主控**声明过**的参数（见 PASSTHROUGH），避免把主控自己的参数
    （--dry-run / --run-dir 等）误传给 step。
    """
    out = []
    for attr, owner, flag, takes_value in PASSTHROUGH:
        if owner != step_id:
            continue
        val = getattr(args, attr, None)
        if val is None or val is False:
            continue
        if takes_value:
            out.extend([flag, str(val)])
        else:
            out.append(flag)
    # --pre-clean 命中节点 9 时强制清理
    if step_id == "9" and args.pre_clean and "--force" not in out:
        out.append("--force")
    return out


def print_chain(args):
    print("链条（README §5 的编排流程）：")
    print()
    for sid, mod, name, why in CHAIN:
        print(f"  [{sid}] {name:14s} {mod:28s} {why}")
    print()
    print("  （无节点 3：实机复核证明「跨过第一层」不存在）")


def run_one(args, log, prog, run_dir, ids):
    """跑**一个**程序的完整链条。

    返回 (results, watchdog_fired)。`both` 模式会对 ok-ww 与 ok-nte 各调一次。

    ⚠️ 抽成函数的原因：`--target both` 要求两个程序**先后各跑一遍完整链条**，
    而不是把两个程序的节点混在一条链里 —— 它们的节点序列不同、
    state.json 里的 program 只能存一个值。抽出来才能干净地跑两轮。
    """
    # --- 逐节执行 -----------------------------------------------------
    # 整轮墙钟上限（用户裁定：半小时，到点关窗口 + 关游戏）。
    # 粒度是「节」：每节之间检查一次。若某一节自己挂住，主控会一直等它 ——
    # 故 step8 的 --total-timeout 由下面推导出**不超过剩余时间**，两者互补。
    deadline = watchdog.Deadline(args.run_timeout, log=log)
    deadline.begin()
    if args.run_timeout > 0 and not args.no_watchdog:
        log(f"\n[时间上限] 整轮 {args.run_timeout:.0f}s（{args.run_timeout/60:.0f} 分钟）"
            f"，到点关闭目标程序窗口与游戏")
    elif args.no_watchdog:
        log("\n[时间上限] 已停用（--no-watchdog）")
    watchdog_fired = None

    results = []
    for sid in ids:
        mod = dict((c[0], c[1]) for c in CHAIN)[sid]
        name = dict((c[0], c[2]) for c in CHAIN)[sid]

        # --- 到点检查 ---------------------------------------------------
        if deadline.seconds > 0 and not args.no_watchdog and deadline.expired():
            log("\n" + "=" * 74)
            log(f"[主控] 整轮时间上限到了（{deadline.describe()}）—— 执行超时收尾")
            log("=" * 74)
            watchdog_fired = watchdog.force_close(
                prog, reason="run-timeout", log=log,
                dry_run=args.dry_run, close_game=not args.keep_game)
            state = context.RunState.load(run_dir, must_exist=False)
            state.set("watchdog", watchdog_fired)
            state.set("result", "timeout")
            state.set("result_detail",
                      f"整轮超过 {deadline.seconds:.0f}s 上限，已强制收尾")
            state.save()
            _report_after_timeout(prog, log)
            break

        cmd = [args.python, "-m", f"orchestrator.steps.{mod}",
               "--run-dir", run_dir]
        if args.dry_run:
            cmd.append("--dry-run")
        cmd.extend(step_specific_args(args, sid))
        cmd.extend(args.step_arg)

        # --- 把「剩余时间」传给节点 8，避免它跑过总上限 -------------------
        # 用户裁定单程序半小时；step8 自己的兜底不能比总上限还长，
        # 否则总上限只能在节点 8 **返回之后**才生效。
        if (sid == "8" and args.run_timeout > 0 and not args.no_watchdog
                and "--total-timeout" not in cmd):
            remain = deadline.remaining()
            if remain > 0:
                cmd.extend(["--total-timeout", f"{remain:.0f}"])
                log(f"  [时间上限] 节点 8 兜底设为剩余 {remain:.0f}s")

        log("\n" + "=" * 74)
        log(f"[主控] 启动节点 {sid} {name}")
        log(f"  [时间上限] {deadline.describe()}")
        if args.show_cmd:
            log(f"  $ {' '.join(cmd)}")
        log("=" * 74)

        t0 = time.time()
        r = subprocess.run(cmd, cwd=context.ROOT)
        elapsed = time.time() - t0

        results.append((sid, name, r.returncode, elapsed))
        log(f"\n[主控] 节点 {sid} 退出码 {r.returncode}  用时 {elapsed:.1f}s")

        if r.returncode != 0:
            # --- 节点是因为「整轮到点」才失败的吗？------------------------
            # ⚠️ 实测踩过（2026-10-17）：到点检查（上面 :224）只在**每节开始前**
            # 跑；节点 8 会拿到「剩余时间」当自己的兜底（见下面 :249），于是
            # 它**抢先**在总上限到期时报 timeout 返回 3，主控这里直接 break ——
            # :228 的 force_close **永远没机会执行**，游戏就留在场上。
            # 实测现场留下 pythonw.exe + NTEGame.exe + HTGame.exe 共 3 个进程。
            # ⇒ 这里必须补上同一条收尾路径。
            if (deadline.seconds > 0 and not args.no_watchdog
                    and deadline.expired()):
                log(f"[主控] 节点 {sid} 未通过，且整轮时间上限已到"
                    f"（{deadline.describe()}）—— 执行超时收尾")
                watchdog_fired = watchdog.force_close(
                    prog, reason="run-timeout", log=log,
                    dry_run=args.dry_run, close_game=not args.keep_game)
                state = context.RunState.load(run_dir, must_exist=False)
                state.set("watchdog", watchdog_fired)
                state.set("result", "timeout")
                state.set("result_detail",
                          f"整轮超过 {deadline.seconds:.0f}s 上限，已强制收尾"
                          f"（节点 {sid} 报回 timeout）")
                state.save()
                _report_after_timeout(prog, log)
                break

            log(f"[主控] 节点 {sid} 未通过 —— 链条在此停手")
            log(f"  => 修好代码后**只重跑这一节**：")
            log(f"     python -m orchestrator.steps.{mod} --run-dir \"{run_dir}\"")
            log(f"  => 全链续跑：")
            log(f"     python -m orchestrator.steps.main --resume --run-dir \"{run_dir}\" --from {sid}")
            if not args.keep_going:
                break
            log("  [--keep-going] 按参数继续下一节")

    return results, watchdog_fired


def _report_after_timeout(prog, log):
    """超时收尾之后复检一次，把「关没关干净」如实说出来。

    ⚠️ 为什么不信任 force_close 的返回值：它返回的 `killed_game` 列表只统计
    **强杀**的进程。游戏 launcher（`NTEGame.exe`）收到 WM_CLOSE 后会**自己
    体面退出**，于是 `killed_game` 是空的，但游戏其实已经清干净了
    （实测 2026-10-16/17 两次都是这样，见 FAULT #13 的措辞教训）。
    ⇒ 一律**回读现场**再下结论，绝不拿「没强杀」当「没清掉」。
    """
    try:
        left_t = window.running(prog)
    except Exception:  # noqa: BLE001
        left_t = []
    try:
        left_g = watchdog.game_processes(prog)
    except Exception:  # noqa: BLE001
        left_g = []

    if not left_t and not left_g:
        log("[超时收尾] 复检：目标程序与游戏均已退出 —— 收尾干净")
    else:
        if left_t:
            log(f"[超时收尾] ⚠ 目标程序仍有 {len(left_t)} 个进程存活："
                f"{[(n, i) for n, i, _ in left_t]}")
        if left_g:
            log(f"[超时收尾] ⚠ 游戏仍有 {len(left_g)} 个进程存活："
                f"{[(n, i) for n, i, _ in left_g]}")
        log("[超时收尾] 收尾不干净，需要人工处理："
            "python -X utf8 -m orchestrator.steps.main --target "
            f"{prog.key} --pre-clean")


def main(argv=None):
    args = build_parser().parse_args(argv)

    # --- 多目标（`--target ww,nte` / `all` / `both`）----------------------
    # ⚠️ 必须在**一个**运行目录下分几轮，且每轮要接着用 state.json ——
    # 但 state.json 的 program 只能存一个值，所以每轮靠子进程重新指定。
    # 这里不递归调用 main()（会重新算 run_dir、重新写日志头），
    # 而是显式做多遍：每遍算出自己的 prog 与 run_dir，串行跑。
    #
    # 解析放在 --list 之前：拼错一个 key 时，`--list` 也该当场报错，
    # 而不是先打印一张链条表、等真跑起来才发现目标不存在。
    picked = None
    if args.target:
        try:
            picked = targets.parse(args.target)
        except targets.TargetError as e:
            raise SystemExit(f"[--target] {e}")

    if args.list:
        print_chain(args)
        return 0

    ids = selected_steps(args)

    if picked and len(picked) > 1:
        return run_multi(args, ids, picked)

    return run_single(args, ids)


def run_multi(args, ids, order):
    """按 `order` 逐个程序各跑一轮完整链条。

    任一程序失败不影响后面的继续（用户裁定：可无人值守）。
    `order` 来自 targets.parse()：可以是 2 个，也可以是拿 3、4 个——
    以后加应用**不用改这里**，只要 programs.ALL 里有它。
    """
    root_run_dir = (os.path.abspath(args.run_dir) if args.run_dir and not args.resume
                    else context.new_run_dir())
    os.makedirs(root_run_dir, exist_ok=True)
    log = context.Log(os.path.join(root_run_dir, "chain.log"))
    log("=" * 74)
    log(f"串联运行（{len(order)} 个程序）：{targets.describe(','.join(order))}")
    log(f"运行目录 {root_run_dir}")
    log("=" * 74)
    log("每个程序各跑一遍完整链条，各自独立计时（各自半小时上限），"
        "互不影响：一个失败也会继续跑下一个。")

    overall = []
    for idx, key in enumerate(order, 1):
        # 每轮一个子目录，避免几轮的节点日志互相覆盖 —— 否则事后分不清
        # step8.log 是哪个程序的（各轮的节点号完全相同）。
        sub_dir = os.path.join(root_run_dir, key)
        os.makedirs(sub_dir, exist_ok=True)
        sub = argparse.Namespace(**vars(args))
        sub.target = key
        sub.run_dir = sub_dir
        sub.resume = False           # 新目录，不能沿用 --resume 的定位
        prog = programs.get(key)
        log("\n" + "#" * 74)
        log(f"# 串联第 {idx} 轮：{prog.display}（{key}）")
        log(f"# 运行目录 {sub_dir}")
        log("#" * 74)
        t0 = time.time()
        rc = run_single(sub, selected_steps(sub))
        dt = time.time() - t0
        overall.append((key, prog.display, rc, dt))
        log(f"\n[串联] {prog.display} 结束，退出码 {rc}，用时 {dt:.0f}s")

    log("\n" + "=" * 74)
    log("串联汇总")
    log("=" * 74)
    for key, disp, rc, dt in overall:
        log(f"  {disp:8s} 退出码 {rc}  {dt/60:.1f} 分钟  "
            f"{'通过' if rc == 0 else '未通过'}")
    log(f"运行目录 {root_run_dir}")

    # --- 跨程序残留复检 ---------------------------------------------------
    # ⚠️ 为什么必须单独做一遍：每轮的节点 9 只看**自己那个程序**的进程。
    # 实测 ok-nte 正常跑完会关掉游戏本体 HTGame.exe，却把 launcher
    # NTEGame.exe 留在后台（FAULT #31）。跑 ok-ww 那轮更看不见它。
    # 全部跑完后统一查一次，才能说清「到底还剩什么」。
    log("-" * 74)
    log(f"[串联复检] {len(order)} 个程序及其游戏的最终残留")
    residue = {}
    for key, disp, _rc, _dt in overall:
        prog = programs.get(key)
        t = window.running(prog)
        g = watchdog.game_processes(prog)
        residue[key] = {"target": [(n, i) for n, i, _ in t],
                        "game": [(n, i) for n, i, _ in g]}
        log(f"  {disp:8s} 程序 {len(t)} 个 {residue[key]['target']}"
            f"  游戏 {len(g)} 个 {residue[key]['game']}")
    left = sum(len(v["target"]) + len(v["game"]) for v in residue.values())
    if left:
        log(f"  [注意] 仍有 {left} 个进程存活。按 Q3 正常完成不主动杀；")
        log(f"         要清干净请跑：python -X utf8 -m orchestrator.steps.main "
            f"--target {','.join(order)} --pre-clean")
        log(f"         （或对单一程序跑 step9_cleanup --force）")
    else:
        log(f"  [OK] {len(order)} 个程序及其游戏均已自行退干净")
    log("=" * 74)
    log.close()
    bad = [o for o in overall if o[2] != 0]
    if len(bad) == len(overall):
        return 3
    if bad:
        return bad[-1][2] or 3
    return 0


def run_single(args, ids):
    # --- 运行目录 -----------------------------------------------------
    if args.run_dir and not args.resume:
        run_dir = os.path.abspath(args.run_dir)
    elif args.resume:
        run_dir = context.resolve_run_dir(args, create=False)
    else:
        run_dir = context.new_run_dir()

    os.makedirs(run_dir, exist_ok=True)
    log = context.Log(os.path.join(run_dir, "chain.log"))

    # --- 目标程序：写入 state.json，**全链共享** -------------------------
    # 放在开跑之初（而不是每节命令行）：每节都是独立子进程，
    # state.json 是它们唯一的共享通道；写一次，8 个节点都读得到。
    state = context.RunState.load(run_dir, must_exist=False)
    prog = context.resolve_program(state, args, log=log)
    if args.target:
        # 显式 --target 覆盖 state.json（允许改指另一个程序重跑）
        last = state.get("program")
        if last and last != prog.key:
            log(f"[目标程序] 由 {last} 改为 {prog.key}（--target 覆盖）")
        state.set("program", prog.key)
        state.save()
    elif not state.get("program"):
        state.set("program", prog.key)
        state.save()

    log("=" * 74)
    log("断点式编排主控")
    log(f"运行目录 {run_dir}")
    log(f"目标程序 {prog.display}（{prog.key}）")
    log(f"节点序列 {ids}   dry_run={args.dry_run}")
    log(f"解释器   {args.python}")
    log("=" * 74)
    log("\n链条：")
    for sid, mod, name, why in CHAIN:
        mark = ">>" if sid in ids else "  "
        log(f" {mark} [{sid}] {name:14s} {why}")

    if args.dry_run:
        state.set("dry_run", True)
        state.save()

    # --- 前置清理 -----------------------------------------------------
    if args.pre_clean:
        # ⚠️ 清理必须针对**本次的目标程序**：清理 ok-ww 却跑 ok-nte 会
        # 把没在用的那个程序的残留当成本次前提，且真正该清的没清。
        log(f"\n[前置清理] 独占式前提：清掉 {prog.display} 残留进程")
        cmd = [args.python, "-m", "orchestrator.steps.step9_cleanup",
               "--run-dir", run_dir, "--force"]
        if args.dry_run:
            cmd.append("--dry-run")
        r = subprocess.run(cmd, cwd=context.ROOT)
        if r.returncode != 0:
            log(f"  [警告] 前置清理返回 {r.returncode}（继续）")

    results, watchdog_fired = run_one(args, log, prog, run_dir, ids)

    # --- 汇总 ---------------------------------------------------------
    state = context.RunState.load(run_dir, must_exist=False)
    log("\n" + "=" * 74)
    log("主控汇总")
    log("=" * 74)
    log(state.summary())

    failed = [r for r in results if r[2] != 0]
    log("")
    if watchdog_fired:
        log(f"⚠ 整轮时间上限先到 —— 已强制收尾："
            f"关目标窗口 {len(watchdog_fired.get('closed_windows') or [])} 个，"
            f"关游戏窗口 {len(watchdog_fired.get('closed_game_windows') or [])} 个，"
            f"杀目标进程 {len(watchdog_fired.get('killed_target') or [])} 个，"
            f"杀游戏进程 {len(watchdog_fired.get('killed_game') or [])} 个")
        log(f"  （明细见 state.json 的 watchdog 字段）")
    elif not failed:
        log("全部节点通过")
    else:
        log(f"{len(failed)} 个节点未通过："
            + ", ".join(f"{s}({n}) 退出码{c}" for s, n, c, _ in failed))
    log(f"运行目录 {run_dir}")
    log(f"  状态    {os.path.join(run_dir, 'state.json')}")
    log(f"  主控日志 {os.path.join(run_dir, 'chain.log')}")
    log(f"  各节日志 step<N>.log；抓图 shots/")
    log("=" * 74)

    log.close()
    if watchdog_fired:
        return 3
    if failed:
        return failed[-1][2] or 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
