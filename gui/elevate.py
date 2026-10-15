"""gui.elevate — Windows UAC 自提权（进程重启法）

**为什么是「重启一个提权副本」而不是别的手段**：Windows 不允许一个正在运行的
进程给自己提权 —— 令牌在 CreateProcess 时就定了。唯一可行的路径是
`ShellExecuteW(..., "runas", ...)` 拉起**同一份代码的新进程**，让 UAC 在那个
新进程创建时弹窗；新进程带上 `--elevated` 标记，由它继续跑 GUI。

**为什么放在入口 `gui/__main__.py`、而不是 `gui/app.py` 里**：tkinter 的
Tk() 一旦建出来，再起子进程就会有两个窗口一闪而过，而且父进程要等子进程
退出才能收尾。所以在 import tkinter **之前**提权，父进程干脆什么都不做，
只等新进程结束并把它的退出码原样返回。

**这条不能破**：`sys.executable` 被重写成 pythonw.exe 时，`sys.argv[0]` 不再
是磁盘上的真实脚本路径。所以重启用**命令行重建**（模块模式 `-m gui` 或脚本
路径直接传），而不是简单地把 `sys.argv` 转手。见 `relaunch_args()`。

**argv 编码走的是 Unicode**（`ShellExecuteW` 的 lpParameters 是 UTF-16 宽字符），
中文路径与中文参数都不会乱码；但 GetCommandLineW 是 ANSI 侧的命令行重建，
故仍通过 `subprocess.list2cmdline` 生成 Windows 标准引号规则，覆盖含空格参数。
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

# 提权副本靠这个标记认出「我已经被提权过了」，从而不再递归重启。
# 它是**内部**参数：命令行上可见、但不进 argparse（见 __main__.py）。
ELEVATED_FLAG = "--elevated"

# 心跳参数：副本启动后立刻把自己"活着"这件事写进这个文件。
# 父进程靠它区分「UAC 通过且副本存活」与「ShellExecute 谎报成功」。
HEARTBEAT_FLAG = "--heartbeat"

# 等心跳的秒数。UAC 弹窗是**用户交互**，慢是正常的，所以给得宽。
HEARTBEAT_TIMEOUT = 30.0

# 副本启动失败时写的日志名（放在 cwd，也就是仓库根）。
# 父进程在**每次**拉起副本前会先删掉它 —— 否则上一次运行留下的旧日志
# 会被当成这次的失败原因打印出来，把人带偏。
FAILED_LOG = "elevate-failed.log"

# ShellExecuteW 的返回值：> 32 表示成功。常见失败码单独给一句人话。
SE_ERR_ACCESSDENIED = 5
SE_ERR_ASSOCINCOMPLETE = 27
SE_ERR_DDEBUSY = 30
SE_ERR_DDEFAIL = 29
SE_ERR_DDETIMEOUT = 28
SE_ERR_DLLNOTFOUND = 32
SE_ERR_FNF = 2
SE_ERR_NOASSOC = 31
SE_ERR_OOM = 8
SE_ERR_PNF = 3
SE_ERR_SHARE = 26

SW_SHOWNORMAL = 1

_ERROR_TEXT = {
    SE_ERR_FNF: "找不到文件（解释器或脚本路径不对）",
    SE_ERR_PNF: "找不到路径",
    SE_ERR_ACCESSDENIED: "访问被拒绝",
    SE_ERR_OOM: "内存不足",
    SE_ERR_DLLNOTFOUND: "找不到依赖的 DLL",
    SE_ERR_SHARE: "文件被占用（共享冲突）",
    SE_ERR_ASSOCINCOMPLETE: "文件关联不完整",
    SE_ERR_DDETIMEOUT: "DDE 超时",
    SE_ERR_DDEBUSY: "DDE 忙",
    SE_ERR_DDEFAIL: "DDE 失败",
    SE_ERR_NOASSOC: "没有可用于该扩展名的程序关联",
}


def _quiet_remove(path):
    """删文件，失败就算了（临时文件，不值得为一个残留把启动流程搞崩）。"""
    try:
        os.remove(path)
    except OSError:
        pass


def parse_internal_args(argv):
    """摘掉内部参数（--elevated / --heartbeat <path>），返回 (剩余 argv, 心跳路径)。

    这些参数由本模块自己产生、也由它自己消费，**不能进 argparse** ——
    否则用户会看到不属于他们的选项，而且 argparse 见到未知参数会直接退出。
    """
    rest = []
    heartbeat = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == ELEVATED_FLAG:
            i += 1
            continue
        if a == HEARTBEAT_FLAG:
            if i + 1 < len(argv):
                heartbeat = argv[i + 1]
                i += 2
                continue
            i += 1
            continue
        if a.startswith(HEARTBEAT_FLAG + "="):
            heartbeat = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return rest, heartbeat


def beat(path):
    """副本打招呼：写心跳文件。父进程在等它。"""
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("alive")
    except OSError:
        pass


def is_admin():
    """本进程是否已提权。

    这里**故意不 import orchestrator.win32** —— GUI 与编排必须解耦
    （见 gui/runner.py 开头第 3 条）：GUI 的入口不该因为编排代码坏了而开不了。
    IsUserAnAdmin 虽然文档上被标记 deprecated，但它就是读本进程令牌的
    TokenElevation，一条 API 调用，没有副作用，且不依赖任何第三方库。
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        # 非 Windows / 异常时**保守地当作已提权**，避免在别的平台上反复自重启。
        return True


def relaunch_args(extra=None):
    """构造提权副本的命令行参数（不含 exe 本身）。

    两种情况都要能自重启：

        python -m gui            -> argv[0] 是 gui 包的 __main__.py，属模块运行
        python gui\\__main__.py    -> argv[0] 是真实脚本路径
        python gui\\__main__.py --only 8

    `-X utf8` 跟着一起传：主脚本靠它把 stdout 钉成 UTF-8（中文日志不乱码），
    提权副本没有理由丢掉这个设定。
    """
    argv0 = sys.argv[0]
    args = [sys.executable, "-X", "utf8"]

    # 关键：`python -m gui` 时 argv[0] **也是** ...\gui\__main__.py 的绝对路径，
    # 它确实是个存在的 .py 文件 —— 只看 isfile 会误判成脚本模式。而模块模式下
    # 那个文件是**包内部**的 __main__.py，当脚本跑会丢掉包上下文。
    # 判别方法：模块模式下 __package__ 有值（'gui' 或 'gui.__main__'）。
    if __package__:
        pkg = __package__.rsplit(".", 1)[0] or __package__
        args += ["-m", pkg]
    elif argv0 and os.path.isfile(argv0) and os.path.basename(
            argv0).lower().endswith(".py"):
        # 脚本模式：直接把路径传给新进程，它自己会 _ensure_repo_root_on_path
        args.append(os.path.abspath(argv0))
    else:
        # 兜底：认不出形态时按包名走（本仓库的用法就是 python -m gui）
        args += ["-m", "gui"]

    args.append(ELEVATED_FLAG)
    if extra:
        # 调用方（如命令行快捷方式）自己指定了参数：用它，但要剔掉内部标记，
        # 否则父进程带着 --elevated 重启一次，副本再带着它重启，无限递归。
        args += [str(a) for a in extra if a != ELEVATED_FLAG]
    else:
        # 默认沿用本进程的参数，但要剔掉三类不该继承的：
        #   --elevated   已由上面统一加上，重复会导致歧义
        #   --heartbeat  心跳路径是**这一次**重启专用的，重传会指向旧文件
        #   --no-elevate 是"别提权"的意思，副本不该再看到它
        inherited, _hb = parse_internal_args(sys.argv[1:])
        args += [a for a in inherited if a != "--no-elevate"]
    return args


def _timeout_message(args, here, beat):
    """等不到心跳时，给一条**能直接拿去复现**的说明。

    不要只说"可能被杀软拦了"—— 那没法验证。把提权副本的确切命令行原样打出来，
    用户可以在**管理员终端**里粘一遍，看到真正的报错。
    """
    err_log = os.path.join(here, FAILED_LOG)
    lines = [
        "UAC 通过了，但提权副本没有回报心跳（启动后立刻退出）。",
        "",
        "提权副本本来要执行的命令（已含解释器与全部参数）：",
        "  " + subprocess.list2cmdline(args),
        "",
        "请开一个**管理员** PowerShell，把上面那行原样粘进去跑 —— ",
        "python 的报错会直接显示在屏幕上，那就是真正的原因。",
    ]
    if os.path.exists(err_log):
        try:
            with open(err_log, encoding="utf-8", errors="replace") as f:
                tail = f.read().strip()
            if tail:
                lines += ["", f"副本留下的日志（{err_log}）:", tail]
        except OSError:
            pass
    lines += ["", "也可以直接改用管理员终端手动启动本程序。"]
    return "\n".join(lines)


def relaunch_as_admin(argv=None, cwd=None):
    """用 "runas" 动词重启本程序，弹 UAC，并**确认真的是副本起来了**。

    返回 (started, message)：

        started=True   UAC 已通过且副本已确认存活（本进程应当**立刻退出**）
        started=False  UAC 被拒、启动失败、或副本起来又立刻死了

    ⚠️ **`ShellExecuteW` 的返回值不能单独当成功判据**。实测：即使 UAC 弹窗被
    关掉、或子进程因 DLL 初始化失败（0xc0000142）当场毙命，它**照样返回 42**
    （>32 = "success"）。所以这里加了"心跳确认"：让副本在启动时先写一个
    心跳文件，父进程等它出现才认成功。没有心跳 = 副本没活下来，走降级路径。

    **父进程不接管子进程的 stdout**：提权后的进程有自己的控制台/无控制台，
    管道跨不过 UAC 边界。所以这里只负责拉起 + 等心跳，不做输出转发。
    """
    if os.name != "nt":
        return False, "自提权只在 Windows 上有意义。"

    args = relaunch_args(argv)
    here = cwd or os.getcwd()

    # 心跳文件：传给副本，让它一启动就写。父进程等它 —— 这是唯一能区分
    # "UAC 通过且副本活着" 与 "ShellExecute 撒谎说成功" 的信号。
    token = f"{os.getpid()}-{int(time.time() * 1000)}"
    beat = os.path.join(here, f".elevate-heartbeat-{token}.tmp")

    # ⚠️ 心跳参数必须放在**目标模块之后**（args 末尾），不能插在 -X 前面。
    # python 把 `-m gui` 之前的一切都当成**它自己的**选项：
    #     python.exe --heartbeat x -X utf8 -m gui
    #     -> unknown option --heartbeat，退出码 2，副本当场死，
    #        于是父进程永远等不到心跳。
    # 正确形态（--heartbeat 是本程序自己的参数，属于 -m gui 之后）：
    #     python.exe -X utf8 -m gui --elevated --heartbeat x
    args = list(args) + [HEARTBEAT_FLAG, beat]

    # ⚠️ lpParameters **不含** exe 本身：exe 走 lpFile，其余才是参数。
    # 若把 args[0] 也拼进去，子进程会把 python.exe 当成脚本路径，
    # 于是 python 去找一个叫 "D:\...\python.exe" 的脚本、当场失败 ——
    # 表现为"UAC 通过但副本立刻退出"，且 ShellExecuteW 照样返回 42。
    params = subprocess.list2cmdline(args[1:])
    _quiet_remove(beat)
    # 清掉上一次的失败日志：它是**本次**失败的唯一证据来源，
    # 留着旧的会把本次的排查带偏。
    _quiet_remove(os.path.join(here, FAILED_LOG))

    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = wt.HINSTANCE       # 文档：返回值是 HINSTANCE
    shell32.ShellExecuteW.argtypes = [
        wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]

    try:
        r = shell32.ShellExecuteW(None, "runas", args[0], params, here,
                                  SW_SHOWNORMAL)
    except OSError as e:
        return False, f"调用 UAC 失败：{e}"

    code = ctypes.cast(r, ctypes.c_void_p).value or 0
    if code <= 32:
        why = _ERROR_TEXT.get(code, f"ShellExecute 返回 {code}")
        if code == SE_ERR_ACCESSDENIED:
            why = "你在 UAC 弹窗上点了「否」"
        return False, f"提权失败：{why}。"

    # ShellExecute 说成功了 —— 但必须等心跳来证实。
    deadline = time.time() + HEARTBEAT_TIMEOUT
    while time.time() < deadline:
        if os.path.exists(beat):
            _quiet_remove(beat)
            return True, "已取得管理员权限，提权副本已启动。"
        time.sleep(0.1)

    _quiet_remove(beat)
    return False, _timeout_message(args, here, beat)


def banner_text():
    """未提权时给用户看的一段话（控制台/消息框共用措辞）。"""
    return (
        "本程序需要**管理员权限**才能完整工作：\n"
        "  · 节点 1 提权检查会直接失败\n"
        "  · 节点 9 无法终止 ok-ww 残留进程（实测 Access denied）\n\n"
        "自动提权没成功，可以手动来：\n"
        "  右键终端 -> 以管理员身份运行 -> 重新执行同样的命令。"
    )
