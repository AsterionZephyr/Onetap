import ctypes, sys, os
from ctypes import wintypes as wt
k=ctypes.windll.kernel32; a=ctypes.windll.advapi32
k.GetCurrentProcess.restype=wt.HANDLE
k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k.OpenProcess.restype=wt.HANDLE
a.OpenProcessToken.argtypes=[wt.HANDLE,wt.DWORD,ctypes.POINTER(wt.HANDLE)]; a.OpenProcessToken.restype=wt.BOOL
a.GetTokenInformation.argtypes=[wt.HANDLE,ctypes.c_int,ctypes.c_void_p,wt.DWORD,ctypes.POINTER(wt.DWORD)]; a.GetTokenInformation.restype=wt.BOOL
def integ(h):
    tok=wt.HANDLE()
    if not a.OpenProcessToken(h,0x0008,ctypes.byref(tok)): return None
    buf=ctypes.create_string_buffer(64); need=wt.DWORD()
    a.GetTokenInformation(tok,25,buf,64,ctypes.byref(need))
    return ctypes.cast(buf,ctypes.POINTER(wt.DWORD)).contents.value
print("本 shell pid", os.getpid(), "integrity = 0x%X" % (integ(k.GetCurrentProcess()) or 0))
for pid in (33712,):
    h=k.OpenProcess(0x0400,False,pid)
    print(f"GUI pid {pid} handle={h} integrity =", ("0x%X"%integ(h)) if h else "打不开")
