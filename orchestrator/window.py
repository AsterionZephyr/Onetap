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

from . import win32
from .errors import DiscoveryFailure, GuardFailure

# 标题正则（INV-5：绝不用精确相等）。
# 真实标题：`OK-WW v3.6.7 China  - OK-WW`（注意两个空格）。
# 第一层标题是小写 `ok-ww`，故正则必须不区分大小写。
OKWW_TITLE_RE = r"(?i)OK-WW"

# 第二层启动期间的标题是裸 `OK-WW`，就绪后才是完整标题。
READY_TITLE_RE = r"(?i)OK-WW\s+v[\d.]+\s+\w+\s+-\s+OK-WW"

OKWW_EXE = r"E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe"
OKWW_DIR = r"E:\TOOLS\ScriptsGames\ok-ww"

# 窗口就绪的**结构**判据（本次实机新增）。
#
# 为什么不能只看「rect 连续稳定」：第二层刚启动时窗口是 625x625 的一个**空壳**，
# 尺寸照样稳定，抓出来是纯色（实测 1 色），INV-13 拦下 —— 也就是「稳定」不等于
# 「可用」。就绪必须同时满足：
#   - 标题已是完整形态（含版本号）
#   - 尺寸达到可用下限（本机实测正常窗口 1458x800 ~ 1875x1250）
#   - 尺寸连续采样稳定
READY_MIN_WIDTH = 1000
READY_MIN_HEIGHT = 700

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


def find_okww_window(require_ready=False):
    """节点 4：按标题正则发现窗口持有者。

    同时排除第一层的 Tauri 外壳（class `Tauri Window`）——
    它持有的是启动器窗口，不是真正干活的 Qt 窗口。
    """
    pattern = READY_TITLE_RE if require_ready else OKWW_TITLE_RE
    found = [w for w in win32.find_windows(pattern)
             if w[3] != "Tauri Window"]
    if not found:
        return None
    # 窗口持有者是 Qt 自绘窗口
    for hwnd, pid, title, cls in found:
        if cls.startswith("Qt"):
            return {"hwnd": hwnd, "pid": pid, "title": title, "class": cls}
    hwnd, pid, title, cls = found[0]
    return {"hwnd": hwnd, "pid": pid, "title": title, "class": cls}


def okww_running():
    """ok-ww 的两层进程是否还有活的。"""
    procs = win32.list_processes(["pythonw.exe", "ok-ww.exe"])
    root = os.path.normcase(os.path.abspath(OKWW_DIR))
    alive = []
    for name, pid, exe in procs:
        if exe and os.path.normcase(os.path.abspath(exe)).startswith(root):
            alive.append((name, pid, exe))
    return alive


def launch_okww(exe=OKWW_EXE, cwd=None, log=None):
    """节点 2：启动 ok-ww.exe（第一层）。

    第一层会自行检查更新并启动第二层；**全程无需点击**（T-4 / §2.1）。
    """
    if not os.path.isfile(exe):
        raise DiscoveryFailure(f"ok-ww 可执行文件不存在：{exe}")

    existing = okww_running()
    if existing:
        if log:
            log(f"  ok-ww 已在运行：{existing}")
        return False

    if log:
        log(f"  启动 {exe}")
    subprocess.Popen([exe], cwd=cwd or os.path.dirname(exe))
    return True


def wait_for_second_layer(timeout=SECOND_LAYER_TIMEOUT, log=None):
    """节点 4：等待第二层的窗口持有者出现（pythonw.exe 持有 Qt 窗口）。

    实测时间线（全程零点击）：pythonw 21.5s -> Qt 窗口 25.2s -> ok-ww.exe 约 27s 消失。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = find_okww_window()
        if info and info["class"].startswith("Qt"):
            if log:
                log(f"  第二层窗口出现 hwnd={info['hwnd']} pid={info['pid']}")
            return info
        time.sleep(1.0)
    raise DiscoveryFailure(
        f"等待 {timeout:.0f} 秒仍未出现第二层 Qt 窗口。\n"
        f"  当前 ok-ww 进程：{okww_running() if log else '(略)'}")


def wait_for_ready(hwnd, log=None, timeout=READY_TIMEOUT,
                   samples=STABLE_SAMPLES, interval=STABLE_INTERVAL):
    """节点 5：等待窗口就绪。

    就绪 = **标题已是完整形态** 且 **尺寸达到可用下限** 且 **连续采样稳定**。

    本次实机教训：只看「rect 连续稳定」是不够的 —— 第二层刚起来时窗口是
    625x625 的空壳，尺寸同样稳定，抓出来是纯色，要靠 INV-13 才发现不对。
    与其在抓帧阶段失败，不如把「可用」的条件前置到就绪判定里。
    """
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

        info = find_okww_window()
        title = info["title"] if info else ""
        title_ready = bool(re.search(READY_TITLE_RE, title))
        size_ready = (state["width"] >= READY_MIN_WIDTH
                      and state["height"] >= READY_MIN_HEIGHT)

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
        f"等待 {timeout:.0f} 秒窗口仍未就绪。\n"
        f"  => 窗口可能停在应用更新页且尺寸未达下限（{READY_MIN_WIDTH}x"
        f"{READY_MIN_HEIGHT}）。\n"
        f"  => 本次实机观察：首次启动会停在更新页，第二层同时也在运行；"
        f"把窗口拉大或点掉更新页后重试。")


def bring_to_front(hwnd, log=None):
    """节点 7：置前台 + 可用性校验（INV-8 / INV-22）。"""
    from .input import ensure_foreground
    state = ensure_foreground(hwnd, log=log)
    if log:
        log(f"  [OK] 前台 + 可用  {state['width']}x{state['height']}")
    return state
