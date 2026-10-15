import ctypes
from ctypes import wintypes as wt
k=ctypes.windll.kernel32; a=ctypes.windll.advapi32
k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k.OpenProcess.restype=wt.HANDLE
a.OpenProcessToken.argtypes=[wt.HANDLE,wt.DWORD,ctypes.POINTER(wt.HANDLE)]; a.OpenProcessToken.restype=wt.BOOL
a.GetTokenInformation.argtypes=[wt.HANDLE,ctypes.c_int,ctypes.c_void_p,wt.DWORD,ctypes.POINTER(wt.DWORD)]
a.GetTokenInformation.restype=wt.BOOL
k.GetCurrentProcess.restype=wt.HANDLE
def q(h, cls, n):
    tok=wt.HANDLE()
    if not a.OpenProcessToken(h,0x0008,ctypes.byref(tok)): return None
    buf=ctypes.create_string_buffer(n); need=wt.DWORD()
    if not a.GetTokenInformation(tok,cls,buf,n,ctypes.byref(need)): return None
    return ctypes.cast(buf,ctypes.POINTER(wt.DWORD)).contents.value
lv={0x1000:"Low",0x2000:"Medium",0x3000:"High",0x4000:"System"}
print("本 shell: integerity=0x%04X(%s) elevated=%d" % (q(k.GetCurrentProcess(),25,64) or 0,
      lv.get(q(k.GetCurrentProcess(),25,64) or 0,"?"), q(k.GetCurrentProcess(),20,8) or -1))
