"""orchestrator.window — 节点 1~7：环境前提、进程链条、窗口就绪

对应 FRAMEWORK §2.2 的九个节点，本模块覆盖 1、2、4、5、6、7。

节点 3「跨过第一层」**已删除**。本次实机复核证明它不存在：
ok-ww 启动后界面直接落在「关于」页（日志 `MainWindow:show startup version change
on about tab`），`ok-ww.exe` 内部 10 秒后自行启动第二层（`Scheduling auto-start
for 'ok-ww' in 10 seconds`）。首次启动可能停在应用更新页，但那**不是一道关卡** ——
第二层同时在正常运行，框架不需要点它。
"""

import os
import re
import subprocess
import time

from . import programs as programs_mod
from . import win32
from .errors import DiscoveryFailure, GuardFailure

# --- 目标程序（ok-ww / ok-nte）---------------------------------------------
#
# ⚠️ 本模块原先把 ok-ww 的标题正则、exe 路径、工作目录、进程名、窗口类前缀
# **全部硬编码**在自己这里。接入 ok-nte 时若复制粘贴，会得到两份各自漂移的
# 常量 —— 而漂移是**静默**的（路径写错只表现为「找不到进程」，不报错）。
# 故这些值**一律**从 `orchestrator.programs` 取，本模块只留逻辑。
#
# 下面这些模块级名字**保留**为兼容别名：外部（selftest / 历史脚本）曾直接
# 引用 `window.OKWW_TITLE_RE` 之类；别名指向默认程序（ok-ww），行为不变。
_DEFAULT = programs_mod.DEFAULT

OKWW_TITLE_RE = _DEFAULT.loose_title_re
READY_TITLE_RE = _DEFAULT.ready_title_re
OKWW_WINDOW_CLASS_PREFIX = programs_mod.QT_CLASS_PREFIX
OKWW_EXE = _DEFAULT.exe
OKWW_DIR = _DEFAULT.root_dir

# 排除自家窗口：编排 GUI 是 Tk，驱动终端是 ConsoleWindowClass，
# 但**最可靠的判据是 PID** —— 本进程（及其父）自己的窗口永远不是目标程序。
_SELF_PIDS = set()

# 窗口就绪的**结构**判据（默认程序 ok-ww 的值；ok-nte 见 programs.NTE）。
#
# 为什么不能只看「rect 连续稳定」：第二层刚启动时窗口是 625x625 的一个**空壳**，
# 尺寸照样稳定，抓出来是纯色（实测 1 色），INV-13 拦下 —— 也就是「稳定」不等于
# 「可用」。就绪必须同时满足：
#   - 标题已是完整形态（含版本号）
#   - 尺寸达到可用下限（ok-ww 本机实测正常窗口 1458x800 ~ 1875x1250）
#   - 尺寸连续采样稳定
READY_MIN_WIDTH = _DEFAULT.min_width
READY_MIN_HEIGHT = _DEFAULT.min_height


# 就绪判定：连续采样次数与间隔
STABLE_SAMPLES = 3
STABLE_INTERVAL = 1.0

# 等待第二层 / 等待就绪的上限。实测无点击约 21 秒出现第二层（T-4）。
# 但**首次启动**会停在应用更新页，第二层照样运行，窗口进入就绪可能更久，故给足余量。
SECOND_LAYER_TIMEOUT = 300.0
READY_TIMEOUT = 300.0


def check_admin(log=None):
    """节点 1：提权检查。**硬前置**，非管理员直接中止（INV-7）。

    非提权会话杀不掉 ok-ww（实测 Stop-Process -> Access denied）。
    """
    if not win32.is_admin():
        raise DiscoveryFailure(
            "本进程未提权。ok-ww 是 requireAdministrator，非提权会话连清理进程都会被拒。\n"
            "  => 请以**管理员身份**启动运行本框架的终端/宿主后再试。\n"
            "  => 诊断用途可加 --skip-admin-check 跳过（此时不会执行任何清理）。")
    if log:
        log("  [OK] 提权检查通过")


def _self_pids():
    """返回「本编排自己」的 PID 集合（当前进程 + 父进程）。

    为什么要父进程：GUI 通过 `python -m gui` 起子进程跑节点，
    驱动终端也可能是父进程；把它们一并排除，避免**自家窗口**被当成 ok-ww。
    """
    global _SELF_PIDS
    if _SELF_PIDS:
        return _SELF_PIDS
    _SELF_PIDS = {os.getpid()}
    try:
        import ctypes
        from ctypes import wintypes as wt
        k = ctypes.windll.kernel32
        # 伪句柄 -1 的陷阱：这些 API 返回真句柄，可以正常用（对比 win32.is_admin）
        k.CreateToolhelp32Snapshot.restype = wt.HANDLE
        snap = k.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
        if snap and snap != wt.HANDLE(-1).value:
            class PE32(ctypes.Structure):
                _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                            ("th32ProcessID", wt.DWORD),
                            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                            ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                            ("th32ParentProcessID", wt.DWORD),
                            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                            ("szExeFile", ctypes.c_char * 260)]
            pe = PE32()
            pe.dwSize = ctypes.sizeof(PE32)
            me = os.getpid()
            parent = None
            if k.Process32First(snap, ctypes.byref(pe)):
                while True:
                    if pe.th32ProcessID == me:
                        parent = pe.th32ParentProcessID
                        break
                    if not k.Process32Next(snap, ctypes.byref(pe)):
                        break
            k.CloseHandle(snap)
            if parent:
                _SELF_PIDS.add(parent)
    except Exception:
        pass          # 拿不到父进程不影响主逻辑：至少排除了自己
    return _SELF_PIDS


def find_window(program=None, require_ready=False):
    """节点 4：按标题正则发现**目标程序**的窗口持有者。

    程序由 `program` 指定（Program 实例或 key `"ww"`/`"nte"`）；默认 ok-ww，
    与既有调用方行为一致。

    三重排除（FAULT #12 逼出来的，缺一不可）：
      1. **窗口类必须属于本程序**（Program.window_class_matches）。
         ok-ww 的持有者实测恒为 `Qt6111QWindowIcon`、ok-nte 亦为 Qt 系；
         两者的**第一层外壳**都是 `Tauri Window`，它持有的是启动器、不是
         真正干活的界面（实测本机 `Clash Verge` 也是这个类）。
         但这条判据**不能**写死成「排除 Tauri」：MaaEnd 的主窗口**就是**
         Tauri Window（见 programs.ZMD 的注释）⇒ 写死会让它永远发现不了，
         且只表现为超时。故改为按程序声明，逻辑在 programs.py。
      2. **排除自家进程的窗口**（本进程 + 父进程 PID）。本编排的 GUI 标题
         是「ok-ww 断点式编排 — GUI」，被裸正则 `OK-WW` 命中；ok-ww 退出后
         它会被误判为 ok-ww，而它**能成功抓帧**（不触发任何不变量）
         ⇒ 静默把自己的控制面板当目标。MaaEnd 侧同样如此：本会话 GUI 的
         标题里就含 MaaEnd（FAULT #12 的翻版）。

    返回 None 表示**确实没找到**，绝不返回一个「像目标程序的别的东西」。
    """
    prog = programs_mod.get(program)
    pattern = prog.ready_title_re if require_ready else prog.loose_title_re
    self_pids = _self_pids()
    found = [w for w in win32.find_windows(pattern)
             if w[1] not in self_pids
             and prog.window_class_matches(w[3])]
    if not found:
        return None
    hwnd, pid, title, cls = found[0]
    return {"hwnd": hwnd, "pid": pid, "title": title, "class": cls,
            "program": prog.key}


def find_okww_window(require_ready=False):
    """ok-ww 专用入口（兼容既有调用方）。"""
    return find_window(programs_mod.WW, require_ready=require_ready)


def running(program=None):
    """目标程序的两层进程是否还有活的（按工作目录前缀归属）。"""
    prog = programs_mod.get(program)
    procs = win32.list_processes(prog.process_names)
    return [(name, pid, exe) for name, pid, exe in procs
            if prog.owns_process(exe)]


def okww_running():
    """ok-ww 专用入口（兼容既有调用方）。"""
    return running(programs_mod.WW)


def launch(program=None, exe=None, cwd=None, log=None):
    """节点 2：启动目标程序的第一层。

    第一层会自行检查更新并启动第二层；**全程无需点击**（T-4 / §2.1）。
    ok-ww 第一层约 10 秒后自行退出、ok-nte 同理 —— 真正持窗口的是第二层。
    """
    prog = programs_mod.get(program)
    exe = exe or prog.exe
    if not os.path.isfile(exe):
        raise DiscoveryFailure(f"{prog.display} 可执行文件不存在：{exe}")

    existing = running(prog)
    if existing:
        if log:
            log(f"  {prog.display} 已在运行：{existing}")
        return False

    if log:
        log(f"  启动 {exe}")
    subprocess.Popen([exe], cwd=cwd or os.path.dirname(exe))
    return True


def launch_okww(exe=OKWW_EXE, cwd=None, log=None):
    """ok-ww 专用入口（兼容既有调用方）。"""
    return launch(programs_mod.WW, exe=exe, cwd=cwd, log=log)


def wait_for_second_layer(program=None, timeout=SECOND_LAYER_TIMEOUT, log=None):
    """节点 4：等待第二层的窗口持有者出现。

    实测时间线（ok-ww，全程零点击）：
    pythonw 21.5s -> Qt 窗口 25.2s -> ok-ww.exe 约 27s 消失。
    """
    prog = programs_mod.get(program)
    deadline = time.time() + timeout
    # 单层程序（MaaEnd）：没有「外壳拉第二层」这一步，进程自己就持窗口。
    # 这里只是把「等窗口出现」与「等第二层出现」合并成同一入口，
    # 免得调用方为程序结构差异写分支。
    single = not prog.has_second_layer
    while time.time() < deadline:
        info = find_window(prog)
        if info:
            if log:
                kind = "窗口" if single else "第二层窗口"
                log(f"  {kind}出现 hwnd={info['hwnd']} pid={info['pid']} "
                    f"class={info['class']}")
            return info
        time.sleep(1.0)
    what = "窗口" if single else "第二层 Qt 窗口"
    raise DiscoveryFailure(
        f"等待 {timeout:.0f} 秒仍未出现{what}（{prog.display}）。\n"
        f"  当前 {prog.display} 进程：{running(prog) if log else '(略)'}")


def wait_for_ready(hwnd, program=None, log=None, timeout=READY_TIMEOUT,
                   samples=STABLE_SAMPLES, interval=STABLE_INTERVAL):
    """节点 5：等待窗口就绪。

    就绪 = **标题已是完整形态** 且 **尺寸达到可用下限** 且 **连续采样稳定**。

    本次实机教训：只看「rect 连续稳定」是不够的 —— 第二层刚起来时窗口是
    625x625 的空壳，尺寸同样稳定，抓出来是纯色，要靠 INV-13 才发现不对。
    与其在抓帧阶段失败，不如把「可用」的条件前置到就绪判定里。
    """
    prog = programs_mod.get(program)
    deadline = time.time() + timeout
    last = None
    stable = 0
    reported_shell = False

    while time.time() < deadline:
        state = win32.window_state(hwnd)
        if state is None:
            raise DiscoveryFailure("窗口在等待就绪期间消失")

        if win32.is_iconic_sentinel(state["left"], state["top"]):
            win32.restore_window(hwnd)
            time.sleep(0.6)
            last, stable = None, 0
            continue

        info = find_window(prog)
        title = info["title"] if info else ""
        title_ready = prog.title_matches(title, ready=True)
        size_ready = (state["width"] >= prog.min_width
                      and state["height"] >= prog.min_height)

        sig = (state["left"], state["top"], state["width"], state["height"], title)
        stable = stable + 1 if sig == last else 1
        last = sig

        if not (title_ready and size_ready):
            if not reported_shell:
                log and log(f"  等待就绪：当前 {state['width']}x{state['height']} "
                            f"标题=[{title}]（尺寸或标题尚未达就绪形态）")
                reported_shell = True
            time.sleep(interval)
            continue

        if log:
            log(f"  {state['width']}x{state['height']} @ "
                f"({state['left']},{state['top']})  标题=[{title}]")
        if stable >= samples:
            return state
        time.sleep(interval)

    raise DiscoveryFailure(
        f"等待 {timeout:.0f} 秒窗口仍未就绪（{prog.display}）。\n"
        f"  => 窗口可能停在应用更新页且尺寸未达下限（{prog.min_width}x"
        f"{prog.min_height}）。\n"
        f"  => 本次实机观察：首次启动会停在更新页，第二层同时也在运行；"
        f"把窗口拉大或点掉更新页后重试。")


def bring_to_front(hwnd, log=None):
    """节点 7：置前台 + 可用性校验（INV-8 / INV-22）。"""
    from .input import ensure_foreground
    state = ensure_foreground(hwnd, log=log)
    if log:
        log(f"  [OK] 前台 + 可用  {state['width']}x{state['height']}")
    return state
