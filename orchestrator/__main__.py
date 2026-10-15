"""orchestrator.__main__ — 命令行入口

用户决策（Q5）：**一个命令跑到底**，且**必须先 `--dry-run`**。

    python -m orchestrator --dry-run
    python -m orchestrator

退出码：

    0  正常完成
    2  环境前提不成立（未提权、找不到 ok-ww、资产缺失）
    3  一条不变量被破坏（校验失败后停手）
    4  超时（ok-ww 卡在等待状态）
    5  未预期异常 / 用户中断
"""

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m orchestrator",
        description="ok-ww 黑盒编排：启动 -> 导航 -> 点开始 -> 等完成 -> 确认退出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="只做校验与定位，不点击、不等待、不清理（推荐首次运行）")
    p.add_argument("--no-launch", action="store_true",
                   help="不启动 ok-ww.exe，假定它已在运行")
    p.add_argument("--skip-admin-check", action="store_true",
                   help="跳过提权自检。**此时不会执行任何清理**，仅供诊断")
    p.add_argument("--freeze-seconds", type=float, default=180.0,
                   help="计时器冻结多少秒后判超时（默认 180）")
    p.add_argument("--log-dir", default=os.path.join(HERE, "logs"),
                   help="运行日志目录（默认 <repo>/logs）")
    p.add_argument("--out-dir", default=os.path.join(HERE, "logs", "shots"),
                   help="抓图落盘目录（默认 <repo>/logs/shots）")
    p.add_argument("--version", action="version",
                   version="orchestrator 0.1.0")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    from .orchestrator import Orchestrator
    orch = Orchestrator(
        dry_run=args.dry_run,
        log_dir=args.log_dir,
        out_dir=args.out_dir,
        skip_admin_check=args.skip_admin_check,
        no_launch=args.no_launch,
        freeze_seconds=args.freeze_seconds,
    )
    return orch.run()


if __name__ == "__main__":
    sys.exit(main())
