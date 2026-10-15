"""orchestrator.cleanup — 退出与清理（Q3 决策）

用户裁定的清理策略：

  - **正常完成时不杀任何东西**。ok-ww 自己退出（`Exit After Task` 配置驱动），
    游戏也由它自己杀。框架只**确认**，不动手。
  - **只在超时或失败时**杀进程。
  - 杀之前**必须确认该 pid 的可执行路径在目标程序目录下**。

最后一条是硬要求：本机同时有**无关的 python 进程**（如 searxng 的
`pythonw.exe`、`D:\\WORKs\\Anaconda\\pythonw.exe` —— 均为实测在跑的进程），
而目标程序的窗口持有者**恰好也叫 `pythonw.exe`**。按进程名扫会误杀。

## 程序参数化（FAULT #19）

本模块原先把 ok-ww 的**可杀进程名**与**归属目录**写死。现改为从
`orchestrator.programs` 取：进程名 = `Program.process_names`，
归属目录 = `Program.process_prefix`（**不是** `root_dir` ——
`process_prefix` 更精确地指向 `data/apps/<name>` 这一层，
避免把安装根目录下的其它东西算成目标程序）。

⚠️ `process_prefix` 是**可杀范围**的判据。它必须**足够窄**：
ok-ww 与 ok-nte 都装在 `E:\\TOOLS\\ScriptsGames\\` 下，若用共同的父目录
作判据，清理 ok-ww 时会**连带杀掉 ok-nte**。
"""

import os
import time

from . import programs as programs_mod


# 可杀进程名（默认程序 ok-ww）。
# ok-ww 是两层：ok-ww.exe（第一层，通常早已退出）与 pythonw.exe（窗口持有者）。
# 游戏由目标程序自己负责，框架**不**杀游戏 —— 除非用户显式要求。
#
# ⚠️ 保留为模块级常量以兼容既有引用；实际取值一律走 `programs`。
KILLABLE_NAMES = list(programs_mod.DEFAULT.process_names)


def _norm(path):
    return os.path.normcase(os.path.abspath(path)) if path else None


def _is_under(path, root):
    p, r = _norm(path), _norm(root)
    if not p or not r:
        return False
    return p == r or p.startswith(r.rstrip("\\") + "\\")


def _resolve(program=None, names=None, dir_=None):
    """把「程序」解析成 (进程名列表, 归属目录)。

    三条向后兼容规则：
      - `program` 给了 → 用它的 process_names / process_prefix
      - `dir_` 显式给了 → **覆盖** programs 里的目录（历史调用方按 okww_dir 传参）
      - `names` 显式给了 → **覆盖** programs 里的进程名
    """
    prog = programs_mod.get(program) if program is not None else None
    names = list(names) if names else (
        list(prog.process_names) if prog else KILLABLE_NAMES)
    root = dir_ if dir_ else (prog.process_prefix if prog else None)
    return names, root


def plan_cleanup(okww_dir=None, names=None, log=None, program=None):
    """列出**将要**被杀掉的进程。不执行任何动作。

    返回 [(name, pid, exe_path), ...]，只含路径确认在目标目录下的。

    ⚠️ 参数名 `okww_dir` 是**历史遗留**（既有调用方按位置传）。
    新代码请用 `program=`，让目录由 `programs` 决定 ——
    手写目录正是 FAULT #19 那类漂移的来源。
    """
    from . import win32

    names, root = _resolve(program, names, okww_dir)
    root = _norm(root)
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
            log(f"  跳过 {name} pid={pid} —— 路径不在目标目录下：{exe}")
    return chosen


def run_cleanup(okww_dir=None, reason=None, names=None, log=None, dry_run=False,
                program=None):
    """按 plan_cleanup 的结果执行终止。

    返回 {"reason":..., "killed": [...], "skipped": [...]}。
    """
    from . import win32

    plan = plan_cleanup(okww_dir, names=names, log=log, program=program)
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


def confirm_exited(pid, timeout=8.0, interval=0.4, names=None, program=None):
    """确认某 pid 已经消失。返回 True/False。

    ⚠️ 这里**不能**只按 `KILLABLE_NAMES` 筛 —— ok-nte 的第二层可能是
    `python.exe` 而非 `pythonw.exe`（见 programs.NTE 的说明），
    按名字筛会**漏看**仍然活着的进程，于是误报「已退出」。
    故 `names=None` 时扫**全部**进程；`names` 只用于缩小范围的可选优化。
    """
    from . import win32

    if names is None:
        prog = programs_mod.get(program) if program is not None else None
        # 默认（无 program）也要扫全量：宁可多扫，不可漏报仍存活。
        names = list(prog.process_names) if prog else None

    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = win32.list_processes(names)   # names=None ⇒ 全量扫
        alive = any(p == pid for _, p, _ in rows)
        if not alive:
            return True
        time.sleep(interval)
    return False
