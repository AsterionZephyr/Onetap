import ctypes, os, time
from ctypes import wintypes as wt
k=ctypes.windll.kernel32; a=ctypes.windll.advapi32
k.GetCurrentProcess.restype=wt.HANDLE
k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k.OpenProcess.restype=wt.HANDLE
a.OpenProcessToken.argtypes=[wt.HANDLE,wt.DWORD,ctypes.POINTER(wt.HANDLE)]; a.OpenProcessToken.restype=wt.BOOL
a.GetTokenInformation.argtypes=[wt.HANDLE,ctypes.c_int,ctypes.c_void_p,wt.DWORD,ctypes.POINTER(wt.DWORD)]
a.GetTokenInformation.restype=wt.BOOL
def integ(h):
    tok=wt.HANDLE()
    if not a.OpenProcessToken(h,0x0008,ctypes.byref(tok)): return None
    buf=ctypes.create_string_buffer(64); need=wt.DWORD()
    a.GetTokenInformation(tok,25,buf,64,ctypes.byref(need))
    return ctypes.cast(buf,ctypes.POINTER(wt.DWORD)).contents.value
def elevation(h):
    tok=wt.HANDLE()
    if not a.OpenProcessToken(h,0x0008,ctypes.byref(tok)): return None
    buf=ctypes.create_string_buffer(8); need=wt.DWORD()
    a.GetTokenInformation(tok,20,buf,8,ctypes.byref(need))  # TokenElevation
    return ctypes.cast(buf,ctypes.POINTER(wt.DWORD)).contents.value
lv={0x1000:"Low",0x2000:"Medium",0x3000:"High",0x4000:"System"}
for pid,who in [(36240,"本 shell(ops_bash 顶级)"),(33712,"GUI 后台作业")]:
    h=k.OpenProcess(0x0400,False,pid)
    if h:
        i=integ(h)
        print(f"{who:24s} pid={pid:6d} integrity=0x{i:04X}({lv.get(i,'?')}) elevated={elevation(h)}")
    else:
        print(f"{who:24s} pid={pid} 打不开 handle={h}")
# 试着复现写入失败
d=r"E:\TOOLS\ScriptsGames\Onetap\logs\runs\run-20261015-191413"
tmp=os.path.join(d,"_probe_writetest.tmp"); dst=os.path.join(d,"_probe_writetest.txt")
try:
    open(tmp,"w").write("x"); os.replace(tmp,dst)
    print("写入+替换: 成功")
    os.remove(dst)
except Exception as e:
    print("写入+替换失败:", type(e).__name__, e)

