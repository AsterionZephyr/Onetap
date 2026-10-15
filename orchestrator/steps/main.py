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

from . import context

HERE = os.path.dirname(os.path.abspath(__file__))

# 链条定义：节点号 -> (模块名, 中文名, 一句说明)
CHAIN = [
    ("1", "step1_check_admin", "提权检查", "非管理员直接中止（INV-7）"),
    ("2", "step2_launch", "启动 ok-ww.exe", "拉起第一层，它自行启动第二层"),
    ("4", "step4_wait_second_layer", "等待第二层窗口", "Qt 窗口持有者出现"),
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
    g.add_argument("--force-clean", action="store_true",
                   help="[节点 9] 忽略结果，强制走清理路径")
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


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list:
        print_chain(args)
        return 0

    ids = selected_steps(args)

    # --- 运行目录 -----------------------------------------------------
    if args.run_dir and not args.resume:
        run_dir = os.path.abspath(args.run_dir)
    elif args.resume:
        run_dir = context.resolve_run_dir(args, create=False)
    else:
        run_dir = context.new_run_dir()

    os.makedirs(run_dir, exist_ok=True)
    log = context.Log(os.path.join(run_dir, "chain.log"))

    log("=" * 74)
    log("断点式编排主控")
    log(f"运行目录 {run_dir}")
    log(f"节点序列 {ids}   dry_run={args.dry_run}")
    log(f"解释器   {args.python}")
    log("=" * 74)
    log("\n链条：")
    for sid, mod, name, why in CHAIN:
        mark = ">>" if sid in ids else "  "
        log(f" {mark} [{sid}] {name:14s} {why}")

    state = context.RunState.load(run_dir, must_exist=False)
    if args.dry_run:
        state.set("dry_run", True)
        state.save()

    # --- 前置清理 -----------------------------------------------------
    if args.pre_clean:
        log("\n[前置清理] 独占式前提：清掉 ok-ww 残留进程")
        cmd = [args.python, "-m", "orchestrator.steps.step9_cleanup",
               "--run-dir", run_dir, "--force"]
        if args.dry_run:
            cmd.append("--dry-run")
        r = subprocess.run(cmd, cwd=context.ROOT)
        if r.returncode != 0:
            log(f"  [警告] 前置清理返回 {r.returncode}（继续）")

    # --- 逐节执行 -----------------------------------------------------
    results = []
    for sid in ids:
        mod = dict((c[0], c[1]) for c in CHAIN)[sid]
        name = dict((c[0], c[2]) for c in CHAIN)[sid]

        cmd = [args.python, "-m", f"orchestrator.steps.{mod}",
               "--run-dir", run_dir]
        if args.dry_run:
            cmd.append("--dry-run")
        cmd.extend(step_specific_args(args, sid))
        cmd.extend(args.step_arg)

        log("\n" + "=" * 74)
        log(f"[主控] 启动节点 {sid} {name}")
        if args.show_cmd:
            log(f"  $ {' '.join(cmd)}")
        log("=" * 74)

        t0 = time.time()
        r = subprocess.run(cmd, cwd=context.ROOT)
        elapsed = time.time() - t0

        results.append((sid, name, r.returncode, elapsed))
        log(f"\n[主控] 节点 {sid} 退出码 {r.returncode}  用时 {elapsed:.1f}s")

        if r.returncode != 0:
            log(f"[主控] 节点 {sid} 未通过 —— 链条在此停手")
            log(f"  => 修好代码后**只重跑这一节**：")
            log(f"     python -m orchestrator.steps.{mod} --run-dir \"{run_dir}\"")
            log(f"  => 全链续跑：")
            log(f"     python -m orchestrator.steps.main --resume --run-dir \"{run_dir}\" --from {sid}")
            if not args.keep_going:
                break
            log("  [--keep-going] 按参数继续下一节")

    # --- 汇总 ---------------------------------------------------------
    state = context.RunState.load(run_dir, must_exist=False)
    log("\n" + "=" * 74)
    log("主控汇总")
    log("=" * 74)
    log(state.summary())

    failed = [r for r in results if r[2] != 0]
    log("")
    if not failed:
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
    if failed:
        return failed[-1][2] or 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
