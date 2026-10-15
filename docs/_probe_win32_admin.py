"""回归探针：orchestrator.win32 的句柄原型是否健全。

背景（实测故障）：`win32.is_admin()` 曾**恒返回 False**，因为
`kernel32.GetCurrentProcess()` 未声明 restype，ctypes 默认按 c_int（32 位）
截断，把伪句柄 0xFFFFFFFFFFFFFFFF 变成 0xFFFFFFFF，OpenProcessToken
**静默失败**（last error 6 = ERROR_INVALID_HANDLE）。不提权、不报错。

本探针不依赖「当前会话是否提权」，因此**提权与不提权下都应全绿**。

    python docs/_probe_win32_admin.py
"""

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import win32  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    tag = "[OK]" if ok else "[FAIL]"
    print(f"  {tag} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main():
    print("=== 1. GetCurrentProcess 伪句柄不得被截断 ===")
    h = win32.kernel32.GetCurrentProcess()
    raw = h.value if hasattr(h, "value") else h
    # 注意：ctypes 的 restype=wt.HANDLE 会把结果转成 int，所以**不能**用
    # hasattr(h,'value') 判断 restype 是否已声明。真正的判据是**宽度**：
    # 未声明时默认 c_int 会给出 32 位的 0xFFFFFFFF（即 -1 被截断）。
    check("伪句柄宽度为 64 位（未被 c_int 截断）",
          raw == 0xFFFFFFFFFFFFFFFF,
          f"实际 0x{raw & 0xFFFFFFFFFFFFFFFF:016x}；"
          f"若读到 0x00000000ffffffff 即为截断故障复发")

    print("=== 2. OpenProcessToken 必须成功 ===")
    token = wt.HANDLE()
    ok = win32.advapi32.OpenProcessToken(win32.kernel32.GetCurrentProcess(),
                                         win32.TOKEN_QUERY,
                                         ctypes.byref(token))
    check("OpenProcessToken 返回真", bool(ok),
          "失败即为截断故障复发")
    if ok:
        print("=== 3. TokenElevation 可读出 ===")
        elevated = ctypes.c_ulong(0)
        size = ctypes.c_ulong(0)
        r = win32.advapi32.GetTokenInformation(
            token, win32.TokenElevation, ctypes.byref(elevated),
            ctypes.sizeof(elevated), ctypes.byref(size))
        check("GetTokenInformation 返回真", bool(r))
        check("TokenIsElevated 是 0 或 1",
              elevated.value in (0, 1), f"读到 {elevated.value}")
        win32.kernel32.CloseHandle(token)

    print("=== 4. is_admin 与 IsUserAnAdmin 必须一致 ===")
    mine, detail = win32.self_check_admin()
    theirs = bool(ctypes.windll.shell32.IsUserAnAdmin())
    check("两者一致", mine == theirs, f"is_admin={mine} shell32={theirs} / {detail}")
    check("is_admin 返回真值（本会话已提权）", mine is True,
          "未提权时此项会红，属预期")

    print("=== 5. 其余真句柄 API 不得被 -1 污染 ===")
    # OpenProcess/FULL 这类返回**真句柄**，绝不能拿伪句柄 -1 去比
    pid = win32.kernel32.GetCurrentProcessId()
    ph = win32.kernel32.OpenProcess(win32.PROCESS_QUERY_LIMITED_INFORMATION,
                                    False, pid)
    check("OpenProcess(self) 成功", bool(ph), f"pid={pid}")
    if ph:
        check("真句柄 != 伪句柄 -1",
              (ph & 0xFFFFFFFFFFFFFFFF) != 0xFFFFFFFFFFFFFFFF)
        win32.kernel32.CloseHandle(ph)

    print()
    if FAILS:
        print(f"结果：{len(FAILS)} 项未通过 -> {FAILS}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
