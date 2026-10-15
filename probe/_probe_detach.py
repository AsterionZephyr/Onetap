"""探针：验证「完全脱离父进程树」的启动方式。

问题：无人值守长跑不能依赖我的持续在场。若 DSH 桌面应用退出，
我这一轮就结束。`Start-Process` 起的进程父进程是 pwsh（在我的树里），
宿主一退就可能被连带杀掉。

本脚本用 CreateProcess + DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB
起子进程，验证它能否在父进程退出后继续写文件。

用法：
    python probe/_probe_detach.py
"""

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "_detach_probe.txt"

CHILD = r"""
import sys, time
out = sys.argv[1]
with open(out, "w", encoding="utf-8") as f:
    for i in range(10):
        f.write("child %d %s\n" % (i, time.strftime("%H:%M:%S")))
        f.flush()
        time.sleep(1)
"""


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

k32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR,
    ctypes.c_void_p, ctypes.c_void_p,
    wintypes.BOOL, wintypes.DWORD,
    ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
]
k32.CreateProcessW.restype = wintypes.BOOL


def spawn_detached(exe, args, cwd=None, breakaway=True):
    """起一个脱离当前进程树（并在可能时脱离 Job）的进程，返回 pid。"""
    cmdline = subprocess.list2cmdline([exe] + list(args))
    buf = ctypes.create_unicode_buffer(cmdline)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    if breakaway:
        flags |= CREATE_BREAKAWAY_FROM_JOB
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    ok = k32.CreateProcessW(
        None, buf, None, None, False, flags, None,
        str(cwd) if cwd else None,
        ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        if breakaway and err == 5:  # 不允许 breakaway，退回不加该标志
            pid, _ = spawn_detached(exe, args, cwd=cwd, breakaway=False)
            return pid, err
        raise OSError(f"CreateProcessW 失败 err={err}")
    k32.CloseHandle(pi.hProcess)
    k32.CloseHandle(pi.hThread)
    return pi.dwProcessId, 0


def main():
    OUT.unlink(missing_ok=True)
    pid, fell_back = spawn_detached(
        sys.executable, ["-X", "utf8", "-c", CHILD, str(OUT)], cwd=ROOT,
    )
    if fell_back:
        print(f"[探针] breakaway 被拒 (err={fell_back})，已退回普通分离")
    print(f"[探针] 已起脱离进程 pid={pid}")
    print("[探针] 本脚本 2 秒后退出；子进程应继续写满 10 行")
    time.sleep(2)
    if OUT.exists():
        got = OUT.read_text(encoding="utf-8").splitlines()
        print(f"[探针] 2 秒时子进程已写 {len(got)} 行")
    print(f"[探针] 现在退出。pid={pid}")


if __name__ == "__main__":
    main()
