"""检查指定 pid 的完整性级别（提权与否），并对比自己的。

用法：
    python docs/_probe_elev.py <pid>

输出每个进程的 TokenIntegrityLevel：
    0x2000 Medium  = 未提权
    0x3000 High    = 已提权
"""

import ctypes
import ctypes.wintypes as wt
import sys

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008

LEVELS = {0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
          0x2100: "MediumPlus", 0x3000: "High", 0x4000: "System"}


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


def integrity_of(pid):
    k32 = ctypes.windll.kernel32
    adv = ctypes.windll.advapi32

    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, f"OpenProcess 失败 err={k32.GetLastError()}"
    try:
        tok = wt.HANDLE()
        if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None, f"OpenProcessToken 失败 err={k32.GetLastError()}"
        try:
            size = wt.DWORD(0)
            adv.GetTokenInformation(tok, 25, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(tok, 25, buf, size.value,
                                           ctypes.byref(size)):
                return None, f"GetTokenInformation 失败 err={k32.GetLastError()}"
            tml = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
            adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
            adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
            cnt = adv.GetSidSubAuthorityCount(tml.Label.Sid).contents.value
            adv.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
            adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
            rid = adv.GetSidSubAuthority(tml.Label.Sid, cnt - 1).contents.value
            return rid, LEVELS.get(rid, f"0x{rid:x}")
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def main():
    me = ctypes.windll.kernel32.GetCurrentProcessId()
    r, n = integrity_of(me)
    print(f"self  pid={me:<8} integrity=0x{r:04x} ({n})" if r is not None
          else f"self  pid={me} ERR {n}")

    for arg in sys.argv[1:]:
        try:
            pid = int(arg)
        except ValueError:
            print(f"skip {arg!r}: 不是 pid")
            continue
        r, n = integrity_of(pid)
        if r is None:
            print(f"pid={pid:<8} ERR {n}")
        else:
            print(f"pid={pid:<8} integrity=0x{r:04x} ({n})")


if __name__ == "__main__":
    main()
