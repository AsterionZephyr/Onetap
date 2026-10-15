"""orchestrator.cleanup — 退出与清理（Q3 决策）

用户裁定的清理策略：

  - **正常完成时不杀任何东西**。ok-ww 自己退出（`Exit After Task` 配置驱动），
    游戏也由它自己杀。框架只**确认**，不动手。
  - **只在超时或失败时**杀进程。
  - 杀之前**必须确认该 pid 的可执行路径在 ok-ww 目录下**。

最后一条是硬要求：本机同时有**无关的 python 进程**（如 searxng 的
`C:\\Python314\\python.exe`），而 ok-ww 的窗口持有者恰好也叫 `pythonw.exe`。
按进程名扫会误杀。
"""

import os
import time


# 可杀进程名。ok-ww 是两层：ok-ww.exe（第一层，通常早已退出）与 pythonw.exe（窗口持有者）。
# 游戏由 ok-ww 自己负责，框架**不**杀游戏 —— 除非用户显式要求。
KILLABLE_NAMES = ["pythonw.exe", "ok-ww.exe"]


def _norm(path):
    return os.path.normcase(os.path.abspath(path)) if path else None


def _is_under(path, root):
    p, r = _norm(path), _norm(root)
    if not p or not r:
        return False
    return p == r or p.startswith(r.rstrip("\\") + "\\")


def plan_cleanup(okww_dir, names=None, log=None):
    """列出**将要**被杀掉的进程。不执行任何动作。

    返回 [(name, pid, exe_path), ...]，只含路径确认在 ok-ww 目录下的。
    """
    from . import win32

    names = names or KILLABLE_NAMES
    root = _norm(okww_dir)
    if not root:
        return []

    chosen, rejected = [], []
    for name, pid, exe in win32.list_processes(names):
        if _is_under(exe, root):
            chosen.append((name, pid, exe))
        else:
            rejected.append((name, pid, exe))

    if log:
        for name, pid, exe in chosen:
            log(f"  将终止 {name} pid={pid}  ({exe})")
        for name, pid, exe in rejected:
            log(f"  跳过 {name} pid={pid} —— 路径不在 ok-ww 目录下：{exe}")
    return chosen


def run_cleanup(okww_dir, reason, names=None, log=None, dry_run=False):
    """按 plan_cleanup 的结果执行终止。

    返回 {"reason":..., "killed": [...], "skipped": [...]}。
    """
    from . import win32

    plan = plan_cleanup(okww_dir, names=names, log=log)
    result = {"reason": reason, "killed": [], "skipped": []}

    for name, pid, exe in plan:
        if dry_run:
            if log:
                log(f"  [DRY RUN] 不终止 {name} pid={pid}")
            result["skipped"].append((name, pid, exe, "dry-run"))
            continue
        if win32.terminate_process(pid):
            if log:
                log(f"  已终止 {name} pid={pid}")
            result["killed"].append((name, pid, exe))
        else:
            if log:
                log(f"  终止失败 {name} pid={pid}（权限不足？）")
            result["skipped"].append((name, pid, exe, "terminate-failed"))

    return result


def confirm_exited(pid, timeout=8.0, interval=0.4):
    """确认某 pid 已经消失。返回 True/False。"""
    from . import win32

    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = any(p == pid for _, p, _ in win32.list_processes(KILLABLE_NAMES))
        if not alive:
            return True
        time.sleep(interval)
    return False
