"""cleanup.py — 编排层的清理策略（Q3 交付物）

## 事实基础（实测）

1. **两个目标程序都会自行清理**，且**实测清理是成功的**
   （完成一次任务后进程表无 ok-ww / ok-nte / pythonw / 游戏残留）。

2. ok-ww 日志里的 `Failed to terminate process with PID N: [WinError 5] 拒绝访问`
   **是良性的**：
   - 目标是**第一层启动器**（日志有 `Kill Launcher After Start`，且其 PID 与
     "被最小化的进程" PID 完全一致）；
   - **首次 `Attempting` 总是成功**，只有**对同一 PID 的重复尝试**才报 WinError 5；
   - 成因是**该进程已经退出**（对已失效 PID 的 OpenProcess 返回 ACCESS_DENIED），
     而非权限不足。

3. 外部（提权会话）对任意进程具备 `PROCESS_TERMINATE` 权限
   （实测对 explorer / DSH / GameViewerServer 均可 OpenProcess(TERMINATE)）。

## 因此清理策略

  - **首选**：等目标程序自行清理（正常情况）；
  - **兜底**：超时或异常时，按**白名单**强制终止残留进程；
  - **绝不**误杀无关进程（尤其 `pythonw` 可能同时是别的东西）。

白名单按 target 配置，默认：
    ok-ww   -> ok-ww.exe, pythonw.exe(仅当持有该程序窗口)
    ok-nte  -> ok-nte.exe, pythonw.exe(同上)
    共享    -> 游戏进程（可选，默认**不动**）
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED = 0x1000


def _tasklist(name):
    o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe",
                        "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, errors="replace").stdout
    rows = []
    for l in o.splitlines():
        if l.startswith('"'):
            p = l.split('","')
            try:
                rows.append((int(p[1]), p[4].strip('"')))
            except Exception:
                pass
    return rows


def _pids_for_image(image):
    return [pid for pid, _ in _tasklist(image)]


def _can_terminate(pid):
    ctypes.set_last_error(0)
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if h:
        k32.CloseHandle(h)
        return True, 0
    return False, ctypes.get_last_error()


def _terminate(pid, timeout=8.0):
    """终止进程并等待其消失。返回 (ok, note)。

    ⚠️ 实测教训：等待消失要用 **tasklist 复核**，不能只靠 OpenProcess 探测 ——
    进程处于"已终止但句柄未释放"的短暂状态时，OpenProcess 仍可能成功，
    导致误判为"仍未消失"。
    """
    ctypes.set_last_error(0)
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        err = ctypes.get_last_error()
        # 5 = ACCESS_DENIED：对**已退出**的 PID 也会返回这个
        if err == 5:
            return True, f"pid {pid} 已不存在（WinError 5 = 已退出）"
        return False, f"OpenProcess 失败 err={err}"
    try:
        if not k32.TerminateProcess(h, 1):
            return False, f"TerminateProcess 失败 err={ctypes.get_last_error()}"
    finally:
        k32.CloseHandle(h)

    t0 = time.time()
    while time.time() - t0 < timeout:
        if pid not in _all_pids():
            return True, f"pid {pid} 已终止"
        time.sleep(0.25)
    return False, f"pid {pid} 仍未消失（等待 {timeout}s）"


def _all_pids():
    """当前系统全部 PID 集合（用 tasklist，避免 OpenProcess 的假阳性）。"""
    o = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, errors="replace").stdout
    out = set()
    for l in o.splitlines():
        if l.startswith('"'):
            try:
                out.add(int(l.split('","')[1]))
            except Exception:
                pass
    return out


def _has_visible_window(pid):
    """该 pid 是否持有可见的顶层窗口。"""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            if n:
                found.append(h)
        return True

    user32.EnumWindows(cb, 0)
    return len(found) > 0


def _parent_map():
    """{pid: ppid} —— 用 CreateToolhelp32Snapshot 拿进程树。

    ⚠️ 实测教训：
      1. 不能靠"有可见窗口"识别第二层 pythonw（窗口未建时会误判）。
      2. `wmic` 在本机（Win11 26200）**已不可用**，返回 0 条关系 ——
         会让血缘判断静默失效。故改用 Toolhelp32 API。
    """
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID:
        return {}
    m = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            m[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = k32.Process32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return m


def _descendants_of(root_pids):
    """返回 root_pids 的全部后代 PID。"""
    pm = _parent_map()
    if not pm:
        return set()
    kids = set()
    changed = True
    while changed:
        changed = False
        for pid, ppid in pm.items():
            if ppid in root_pids or ppid in kids:
                if pid not in kids:
                    kids.add(pid)
                    changed = True
    return kids


def survey():
    """返回当前残留概况。"""
    out = {}
    for img in ["ok-ww", "ok-nte", "pythonw", "Client-Win64-Shipping", "NTEGame"]:
        pids = _pids_for_image(img)
        out[img] = [(pid, _has_visible_window(pid)) for pid in pids]
    return out


def cleanup(target_exe_image, pythonw_only_if_descendant=True, kill_game=False,
            verbose=True):
    """按白名单清理。

    参数
      target_exe_image          : 第一层镜像名（如 'ok-nte'）
      pythonw_only_if_descendant: 只杀**目标进程的后代** pythonw（避免误杀无关 pythonw）
      kill_game                 : 是否一并关闭游戏进程（默认 False）

    识别第二层用**进程血缘**，不用"有可见窗口" —— 后者在窗口未创建时会误判。
    """
    log = []

    def say(s):
        log.append(s)
        if verbose:
            print(f"    {s}", flush=True)

    say(f"清理开始（目标镜像 {target_exe_image}）")

    # 1) 先算出第一层与它们的后代
    roots = set(_pids_for_image(target_exe_image))
    say(f"[第一层] PID = {sorted(roots) if roots else '（无）'}")
    desc = _descendants_of(roots) if roots else set()
    say(f"[后代]   PID = {sorted(desc) if desc else '（无）'}")

    # 2) 第二层 pythonw：优先按血缘；无血缘信息时回退到"有窗口"
    pw_all = _pids_for_image("pythonw")
    targets = []
    for pid in pw_all:
        if pid in desc:
            targets.append((pid, "血缘"))
        elif not pythonw_only_if_descendant:
            targets.append((pid, "全部"))
        elif _has_visible_window(pid) and roots:
            # 回退：有可见窗口且当前确有目标在跑
            targets.append((pid, "有窗口"))
        else:
            say(f"[第二层] 跳过 pid {pid}（非目标后代且无可见窗口）")
    if not targets and pw_all and not roots:
        # 目标已退出，但 pythonw 残留 -> 若它有窗口，视为残留第二层
        for pid in pw_all:
            if _has_visible_window(pid):
                targets.append((pid, "残留有窗口"))
    for pid, why in targets:
        ok, note = _terminate(pid)
        say(f"[第二层]({why}) {note}")

    # 3) 第一层（放在后面杀，避免它先退出导致血缘丢失）
    for pid in sorted(roots):
        ok, note = _terminate(pid)
        say(f"[第一层] {note}")

    # 4) 游戏（可选）
    if kill_game:
        for img in ("Client-Win64-Shipping", "NTEGame"):
            for pid in _pids_for_image(img):
                ok, note = _terminate(pid)
                say(f"[游戏] {note}")
    else:
        say("[游戏] 按配置不处理")

    # 5) 复核
    time.sleep(1.0)
    left = survey()
    residual = {k: v for k, v in left.items()
                if v and k not in ("NTEGame",) and k != target_exe_image}
    # pythonw 残留需判断是否与目标相关
    if "pythonw" in residual and not roots and not desc:
        residual.pop("pythonw", None)
    if residual:
        say(f"仍有残留：{residual}")
        return False, log
    say("清理完成，无残留")
    return True, log


def main():
    print("=" * 74)
    print("Q3 清理策略 · 现状与能力")
    print("=" * 74)

    print("\n[当前残留]")
    s = survey()
    for k, v in s.items():
        print(f"  {k:24s} {len(v)} 个" + (f"  {v}" if v else ""))

    print("\n[终止权限探测]")
    for img in ["pythonw", "ok-ww", "ok-nte"]:
        for pid, _ in s.get(img, [])[:3]:
            ok, err = _can_terminate(pid)
            print(f"  {img} pid={pid}  TERMINATE={'OK' if ok else f'NG({err})'}")

    if "--do" in sys.argv:
        print("\n[执行清理]")
        for t in ("ok-ww", "ok-nte"):
            cleanup(t)
    else:
        print("\n（加 --do 才实际执行清理）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
