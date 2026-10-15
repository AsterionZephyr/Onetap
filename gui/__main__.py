"""gui.__main__ — 入口

    python -m gui
    python -m gui --dry-run
    python -m gui --only 8

**必须以管理员身份运行**才能让节点 9 真正清理进程；未提权时 GUI 顶部
常驻警告横幅，且不会阻止你编辑代码与查看日志。

本入口会**自动弹 UAC 提权**：检查本进程令牌，未提权就用
`ShellExecuteW("runas")` 重启一份提权副本（标记 `--elevated`），父进程随即
退出、不再持有界面。UAC 被拒 / 无法提权时不会硬失败 —— 降级到"未提权但能开"
的路径（横幅 + 节点 1 跳过），因为改代码和看日志本来就不需要管理员。

    python -m gui               # 自动弹 UAC（推荐）
    python -m gui --dry-run     # 参数会被原样带给提权副本
    python -m gui --no-elevate  # 明确不提权，只开界面

`--elevated` / `--heartbeat` 由本入口自己产生、也由它自己消费，**不进 argparse**。

**import 顺序是刻意的**：`gui.app`（连带 tkinter）延后到闸门之后再导入。
若在闸门之前 import，而 tkinter 又恰好导入失败，进程会在打心跳之前就死掉，
父进程只能看到"没等到心跳"，无从判断原因。详见 `_load_app()`。
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _ensure_repo_root_on_path():
    """让 `python gui/__main__.py` 与 `python -m gui` 都能跑。

    直接执行本文件时，sys.path[0] 是 gui/ 而不是仓库根，`from . import` 会失败。
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)


if __package__ in (None, ""):
    _ensure_repo_root_on_path()
    from gui import elevate            # noqa: E402
else:
    from . import elevate              # noqa: E402


# --------------------------------------------------------------- 副本留痕

def _child_log(msg):
    """把提权副本的启动过程写进 <仓库>/elevate-failed.log。

    副本的 stdout 跨不过 UAC 边界，它死掉时父进程什么都看不到 —— 只看到
    "没等到心跳"。所以副本必须**自己留痕**：父进程超时后会把这份日志
    连同确切的命令行一起打印出来，用户据此就能定位真因。
    """
    import os
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "elevate-failed.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def _load_app():
    """导入真正的 GUI 模块，返回 main 函数。

    **这一步必须晚于闸门。** `gui.app` 会 import tkinter；若在闸门之前导入，
    一旦 tkinter 导入失败（缺 Tcl/Tk、DLL 冲突、杀软拦截……），进程会在
    `elevate.beat()` 之前就死掉，父进程只看到"没等到心跳"，完全不知道原因。
    放到闸门之后，异常能被捕获并写进日志。
    """
    if __package__ in (None, ""):
        from gui.app import main       # noqa: E402
    else:
        from .app import main          # noqa: E402
    return main


# --------------------------------------------------------------- 自提权闸门
#
# 参数在此**手工**过一遍，不调 argparse：argparse 一旦见过 --help 就会
# SystemExit，而那一刻我们还没决定要不要提权 —— 先提权再解析，用户看到的
# 才是提权副本里的帮助输出。

def _is_elevated_child():
    """本进程是不是"被提权拉起的副本"（命令行里有 --heartbeat）。"""
    return elevate.parse_internal_args(sys.argv[1:])[1] is not None


def _gate():
    """返回 (should_run, exit_code)。

    should_run=False 时父进程必须**立刻退出**（提权副本已接手）。
    返回 True 时继续在**本进程**里跑 GUI；exit_code 非 0 表示"提权被拒、
    降级运行"，界面照样开，只是把这个事实带给外层。
    """
    import os

    # 内部参数（--elevated / --heartbeat）先摘掉，剩下的才交给 argparse。
    rest, heartbeat = elevate.parse_internal_args(sys.argv[1:])
    sys.argv = [sys.argv[0]] + rest

    # 本进程是提权副本：**立刻**打心跳，让还在等的父进程知道"我活下来了"。
    # 放在这里（而不是 import gui.app 之后）是刻意的 —— 心跳只代表
    # "副本进程起来了、参数解析正常"，后面界面建不起来是另一回事。
    elevate.beat(heartbeat)

    # --no-elevate：显式放弃提权（调试、或本来就在管理员终端里）
    if "--no-elevate" in rest:
        sys.argv = [sys.argv[0]] + [a for a in rest if a != "--no-elevate"]
        return True, 0

    # 已经是提权副本：不再递归弹 UAC
    if heartbeat is not None:
        return True, 0

    # 已经在管理员终端里：直接跑
    if elevate.is_admin():
        return True, 0

    print("[提权] 当前不是管理员，正在请求 UAC …", flush=True)
    started, msg = elevate.relaunch_as_admin(cwd=os.getcwd())
    print(f"[提权] {msg}", flush=True)

    if not started:
        # 不硬失败：降级为未提权运行，GUI 顶部的红色横幅会说明后果。
        # 退出码 3 供脚本/快捷方式区分"提权失败"，但界面照开。
        print("[提权] 继续以**未提权**方式启动界面（节点 9 将无法清理进程）。",
              flush=True)
        print("       " + elevate.banner_text().replace("\n", "\n       "),
              flush=True)
        return True, 3

    # 提权副本在**另一个**进程里跑界面，它的 stdout 不跨 UAC 边界回传，
    # 所以父进程没有再要做的事，直接退出即可。
    return False, 0


def _run():
    # 副本身份：被提权拉起时命令行里有 --heartbeat。
    # 只有**出错**才写 elevate-failed.log —— 正常启动不该在仓库根留垃圾。
    child = _is_elevated_child()

    run_here, code = _gate()
    if not run_here:
        # 提权副本已接手。父进程无事可做 —— 它的"活儿"就是那次 UAC 弹窗。
        # ShellExecuteW 不给 pid，没法等；父进程退出也不会杀掉提权副本。
        return 0

    try:
        main = _load_app()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print("[启动失败] 导入 GUI 模块时出错：\n" + tb, flush=True)
        if child:
            _child_log(f"--- 提权副本启动 {sys.version.split()[0]} ---")
            _child_log("argv = " + repr(sys.argv))
            _child_log("导入 GUI 模块失败：\n" + tb)
        return 4

    rc = main()
    # code != 0 表示"提权被拒、降级运行"：界面已经跑完了，
    # 退出码把这个事实带给外层脚本/快捷方式，但仍然是正常退出。
    return rc or code


if __name__ == "__main__":
    sys.exit(_run())
