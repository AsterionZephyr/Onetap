"""orchestrator.apps.fos —— MPA / FOS 的专项实现（第 4 个被编排的程序）。

## 它和前三个程序的根本不同：**没有界面可编排**

ok-ww / ok-nte / MaaEnd 都要「进到界面上把任务点起来，再判断它做完了」。
FOS（`E:\\TOOLS\\ScriptsGames\\MPA\\FOS.exe`）不是这样。用户裁定
（2026-10-23）：

    只启动，之后等待就行 —— 它自己退出并清理干净，全程不需要任何识别、
    操作；所以也不要去深扒它的运行逻辑。

故 FOS 的链条里**没有**节点 4~8（不找窗口、不抓帧、不点击、不判画面）：

    1 提权自检 -> 2 启动 -> 3 等它自己退出 -> 9 收尾

第 3 节就是本模块的 `wait_exit`：**只读进程表，一个像素都不碰**。

⚠️ 「不要研究它的内部逻辑」是用户明令。本模块刻意只做两件事：启动一次、
观察进程还在不在。任何「顺手看看它的日志/界面」的改动都是越界。

## 判据：「它跑完了」= 进程表里看不见它了

FOS 是 PyInstaller 单文件打包，运行期会拉起子进程（`MFWUpdater.exe` 等），
而且单文件的 bootloader 有一段「父进程退出、子进程接棒」的空窗。故判据两条，
缺一条都会静默出错：

1. **归属**：exe 路径在 MPA 目录下 **或** 进程名属于 FOS 家族名。
   只看路径会漏掉 bootloader 从 `%TEMP%\\_MEIxxxx` 重新 exec 出来的那份
   （那种进程的 exe 不在 MPA 下，但名字还是 FOS.exe）。
2. **确认**：必须**连续 CONFIRM_SAMPLES 次**采样都为空才算结束。只看一次会
   落进上面那段空窗里 ⇒ 误判「已完成」，框架接着去跑下一个程序，而 FOS 仍在
   动鼠标/游戏 ⇒ 后面两个程序的图像判据全部失真（比直接报错难查得多）。

## 为什么超时不杀、交给节点 9

本模块**不做**清理：超时只回报 `timeout`，由节点 9（共用）按既有口径处理
（`result != completed` ⇒ `cleanup.run_cleanup`）。杀掉一个正在写数据库的程序
要连带考虑它的清理，这不是本模块该决定的事。
"""

import os
import time

from ... import win32

#: 安装目录。进程归属判据 = 「exe 在这个目录下」。
FOS_DIR = r"E:\TOOLS\ScriptsGames\MPA"

#: 第一层可执行文件（Program.exe 与这里必须一致，自检会查）。
FOS_EXE = os.path.join(FOS_DIR, "FOS.exe")

#: FOS 家族进程名（小写）。名字判据是路径判据的**补集**，见模块 docstring 第 1 条。
FOS_PROCESS_NAMES = ("fos.exe", "mfwupdater.exe")

#: 连续这么多次采样都为空，才认为它真的退了（防 bootloader 交接空窗）。
CONFIRM_SAMPLES = 3

#: 采样间隔。1 秒足够灵敏，又不至于把 CPU 采样成噪声。
POLL_SECONDS = 1.0

#: 等待上限。实测一轮 **4379s（≈73 分钟）**，见 docs/HISTORY.md 第 9 轮
#: （run-20261023-055917，节点 3 elapsed 4379.3s）。取 5400s（90 分钟）留 ~23% 余量。
#: ⚠️ 与 `orchestrator/programs.py` 里 FOS 的 `run_timeout=5400.0` **必须一致**：
#: 两个都是独立的闸，任一个更小都会提前掐掉它 —— 而且 GUI 不暴露这两个参数。
WAIT_TIMEOUT_SECONDS = 5400.0

#: 日志里多久报一次「还在等」。
HEARTBEAT_SECONDS = 60.0


def fos_processes():
    """当前算作「FOS 还在跑」的进程，[(name, pid, exe)]；空 = 干净。

    扫**全量**进程表（`names=None`）：FOS 的子进程名不受我们控制，
    按名字筛会漏看（同一个道理见 `win32.list_processes` 的注释）。
    """
    root = os.path.normcase(os.path.abspath(FOS_DIR))
    under_root = root + os.sep
    out = []
    for name, pid, exe in win32.list_processes(None):
        if (name or "").lower() in FOS_PROCESS_NAMES:
            out.append((name, pid, exe))
            continue
        if not exe:
            continue
        if os.path.normcase(os.path.abspath(exe)).startswith(under_root):
            out.append((name, pid, exe))
    return out


def describe(alive):
    """进程列表 -> 一行日志文本（pid 在前，名字太多时截断）。"""
    if not alive:
        return "无"
    head = ", ".join(f"{n}({p})" for n, p, _e in alive[:4])
    if len(alive) > 4:
        head += f" …共 {len(alive)} 个"
    return head


def wait_exit(log, program, timeout=WAIT_TIMEOUT_SECONDS, poll=POLL_SECONDS,
              confirm=CONFIRM_SAMPLES):
    """等 FOS 自己退出；**只读进程表，不碰界面**。

    返回 {"state", "elapsed", "seen", "last"}：

        state="exit"   连续 confirm 次采样为空（正常收场）
        state="timeout" 到点仍在跑（由节点 9 决定怎么收）

    `seen` = 这期间**有没有看见过**它。False 说明连一次都没抓到 —— 那多半是
    启动即失败，节点据此报 failed 而不是 completed（见 step3_wait_exit）。
    """
    prog = program
    t0 = time.time()
    seen = False
    empty = 0
    alive = []
    last_beat = t0
    while True:
        now = time.time()
        elapsed = now - t0
        alive = fos_processes()
        if alive:
            seen = True
            empty = 0
        else:
            empty += 1
            if empty >= confirm:
                return {"state": "exit", "elapsed": elapsed, "seen": seen,
                        "last": []}
        if elapsed >= timeout:
            return {"state": "timeout", "elapsed": elapsed, "seen": seen,
                    "last": alive}
        if now - last_beat >= HEARTBEAT_SECONDS:
            last_beat = now
            if alive:
                log(f"  [{elapsed:5.0f}s] 还在等 {prog.display} 自行退出："
                    f" {describe(alive)}")
            else:
                log(f"  [{elapsed:5.0f}s] 进程已空，"
                    f"确认 {empty}/{confirm} 次")
        time.sleep(poll)
