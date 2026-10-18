"""orchestrator.win32 — Win32 绑定的唯一来源

本模块只做一件事：把用到的 Win32 调用按「返回值即成败」的口径包好。

约束（HANDOFF §2.2）：
  - 判断 Win32 调用成败**只看返回值**，不看 GetLastError（可能是无关调用的残留，实测残留值 203）。
  - 不使用 GetCursorPos（本框架一次都不读光标，INV-16 / §3.6）。
  - 一律使用物理像素（调用方须先声明 per-monitor DPI 感知，见 ensure_dpi_aware）。
"""

import ctypes
import ctypes.wintypes as wt
import re

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# --- 常量 -------------------------------------------------------------

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

SW_RESTORE = 9

# SetWindowPos 的抬升参数：只改 Z 序，不移动/不缩放/不激活
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
HWND_TOP = 0

GA_ROOT = 2

# ALT 虚拟键：用于「抖一下」以解除前台锁（FAULT #29）
VK_MENU = 0x12

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

TOKEN_QUERY = 0x0008
TokenElevation = 20

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 最小化哨兵值（INV-22）
ICONIC_SENTINEL = -32000


# --- 结构体 -----------------------------------------------------------


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte),
                ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


_PUL = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", _PUL)]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


# --- DPI 与提权 -------------------------------------------------------


def ensure_dpi_aware():
    """声明 per-monitor v2 DPI 感知。

    必须在**任何抓帧或坐标换算之前**调用。调用后 GetSystemMetrics(0/1) 返回
    物理像素（本机 2560x1440），与窗口 rect 处于同一坐标系。
    """
    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# --- 提权相关 API 的显式原型 ------------------------------------------
#
# 必须声明 argtypes/restype：ctypes 默认把 restype 当 **c_int（32 位）**，
# 而 HANDLE 是**指针宽度**。64 位下 kernel32.GetCurrentProcess() 返回伪句柄
# (HANDLE)-1 = 0xFFFFFFFFFFFFFFFF，被截断成 0xFFFFFFFF 传给 OpenProcessToken，
# 于是调用**静默失败**（last error 6 = ERROR_INVALID_HANDLE），
# is_admin() 从此**恒返回 False** —— 不提权、不报错。
# 实测：截断句柄 False / 正确句柄 True，见 docs/_probe_win32_admin.py。

kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD,
                                      ctypes.POINTER(wt.HANDLE)]
advapi32.OpenProcessToken.restype = wt.BOOL
advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int,
                                         ctypes.c_void_p, wt.DWORD,
                                         ctypes.POINTER(wt.DWORD)]
advapi32.GetTokenInformation.restype = wt.BOOL


def is_admin():
    """当前进程是否已提权（TRUE = 已提权）。

    读的是**本进程的令牌**，不是「用户会话的权限」。

    注意：openprocesstoken 拿的是**伪句柄** -1，不要喂给它任何**真实句柄**
    —— 同族 API（OpenProcess/QueryFullProcessImageNameW）返回的是真句柄，
    绝不能用 -1 代替。
    """
    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_QUERY, ctypes.byref(token)):
        return False
    try:
        elevated = ctypes.c_ulong(0)
        size = ctypes.c_ulong(0)
        ok = advapi32.GetTokenInformation(
            token, TokenElevation, ctypes.byref(elevated),
            ctypes.sizeof(elevated), ctypes.byref(size))
        if not ok:
            return False
        # TokenElevation 的 TokenIsElevated 字段是 DWORD，非零即已提权
        return bool(elevated.value)
    finally:
        kernel32.CloseHandle(token)


def self_check_admin():
    """返回 (is_admin(), 诊断串)。不抛异常，供巡检与自检用。

    is_admin() 曾经**恒为 False**（句柄截断，见上方注释）。本函数用
    `IsUserAnAdmin` 做交叉校验：两者不一致说明绑定又坏了，
    这时**绝不默认成功**（INV-30），必须显式暴露出来。
    """
    mine = is_admin()
    try:
        theirs = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:                      # pragma: no cover
        return mine, f"交叉校验不可用：{exc}"
    if mine != theirs:
        return mine, (f"提权判定不一致：is_admin()={mine} "
                      f"IsUserAnAdmin()={theirs} —— win32 绑定可能已失效")
    return mine, f"一致（is_admin()={mine}）"


# --- 窗口发现 ---------------------------------------------------------


def get_window_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_pid(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_window_rect(hwnd):
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r


def find_windows(title_pattern):
    """按标题**正则**发现窗口（INV-5：绝不用精确相等）。

    返回 [(hwnd, pid, title, class_name), ...]。hwnd 不缓存，每次重新发现（INV-14）。
    """
    pat = re.compile(title_pattern) if isinstance(title_pattern, str) else title_pattern
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        title = get_window_text(hwnd)
        if title and pat.search(title):
            found.append((hwnd, get_window_pid(hwnd), title, get_class_name(hwnd)))
        return True

    user32.EnumWindows(cb, 0)
    return found


def window_state(hwnd):
    """返回窗口几何与前台/可见状态。"""
    r = get_window_rect(hwnd)
    if r is None:
        return None
    return {
        "rect": (r.left, r.top, r.right, r.bottom),
        "left": r.left, "top": r.top,
        "width": r.right - r.left,
        "height": r.bottom - r.top,
        "iconic": bool(user32.IsIconic(hwnd)),
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "foreground": user32.GetForegroundWindow() == hwnd,
    }


def is_iconic_sentinel(left, top):
    """窗口是否处于最小化哨兵位置（INV-22：置前台成功也可能最小化）。"""
    return left <= ICONIC_SENTINEL or top <= ICONIC_SENTINEL


# --- 前台与遮挡 -------------------------------------------------------


def restore_window(hwnd):
    """ShowWindow(SW_RESTORE)。返回后**必须**由调用方校验 rect（INV-22）。"""
    return bool(user32.ShowWindow(hwnd, SW_RESTORE))


def raise_window(hwnd):
    """把窗口抬到 Z 序最上层（**不激活、不移动、不缩放**）。

    用途：目标窗口被**别的程序的窗口**挡住时，先把它抬上来，让
    `top_window_at` 在目标坐标处真的返回目标窗口，随后「真实点击夺取激活」
    才可能生效（INV-23 与 FAULT #35 的交集，见 input._click_to_activate）。

    只改 Z 序，不改别的程序的任何状态，也不改变焦点。
    """
    return bool(user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def _alt_nudge():
    """按一下再松开 ALT —— 用来向系统「声明」本进程想抢占前台。

    Windows 的前台锁有一条规则：**刚收到用户输入的进程**可以抢前台。
    合成一个 ALT 按键就能满足这条，从而让随后的 SetForegroundWindow 被接受。
    这是 AttachThreadInput 之外的第二手准备。
    """
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 24)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("u", _INPUTunion)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    down = INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTunion(ki=KEYBDINPUT(VK_MENU, 0, 0, 0, None)))
    up = INPUT(type=INPUT_KEYBOARD,
               u=_INPUTunion(ki=KEYBDINPUT(VK_MENU, 0, KEYEVENTF_KEYUP, 0, None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


def set_foreground(hwnd):
    """尝试把窗口提到前台。返回 True 只说明**调用被接受**，不代表窗口可用。

    ⚠️ FAULT #29：裸调 SetForegroundWindow **不够**。
    Windows 有「前台锁」：当**别的进程**持有前台时，本调用会被直接拒绝
    （返回 0），而且**重试同一个调用永远不会成功** —— 实测在 DSH 窗口
    处于前台时，连续 6 次全部失败；DSH 不在前台时第 1 次就成功。

    因此这里按优先级依次尝试三种手段（这是 HANDOFF §5「SetForegroundWindow
    + 每次验证」里被漏掉的后半句）：

      1. 裸 SetForegroundWindow —— 最快，前台本来就是自己或无人竞争时即可；
      2. **AttachThreadInput**：把自己的线程输入队列附加到前台窗口的线程上，
         使本进程被视为「可抢占前台」，再调 SetForegroundWindow，之后解除附加；
      3. **ALT 抖动**：合成一次 ALT 按键，让系统认为刚有用户输入，再调一次。

    返回 True 表示**至少有一次调用被接受**；调用方仍须用 GetForegroundWindow
    自行验证（见 input.ensure_foreground）。
    """
    if user32.SetForegroundWindow(hwnd):
        return True

    # --- 手段 2：AttachThreadInput ---
    fg = user32.GetForegroundWindow()
    if fg:
        my_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        if fg_tid and fg_tid != my_tid:
            attached = bool(user32.AttachThreadInput(my_tid, fg_tid, True))
            try:
                if user32.SetForegroundWindow(hwnd):
                    return True
                # 附加状态下再来一次 ALT 抖动，成功率更高
                _alt_nudge()
                if user32.SetForegroundWindow(hwnd):
                    return True
            finally:
                user32.AttachThreadInput(my_tid, fg_tid, False)

    # --- 手段 3：单独 ALT 抖动 ---
    _alt_nudge()
    return bool(user32.SetForegroundWindow(hwnd))



def foreground_hwnd():
    return user32.GetForegroundWindow()


def top_window_at(x, y):
    """目标屏幕坐标处**最顶层**窗口的根窗口（INV-23）。

    比「ok-ww 在前台」更强：前台窗口可能并未覆盖该坐标。
    """
    hwnd = user32.WindowFromPoint(POINT(int(x), int(y)))
    if not hwnd:
        return 0
    return user32.GetAncestor(hwnd, GA_ROOT)


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def client_to_screen(hwnd, cx, cy):
    """窗口内坐标 -> 屏幕坐标。换算关系为纯平移，无缩放因子（§3.1）。"""
    p = POINT(int(cx), int(cy))
    if not user32.ClientToScreen(hwnd, ctypes.byref(p)):
        return None
    return p.x, p.y


# --- 抓帧 -------------------------------------------------------------


def capture_region(x, y, w, h):
    """BitBlt 抓一块屏幕区域，返回 (bytes BGRA, w, h) 或 None。

    注意（INV-17）：越界抓取**会成功返回**并产出全黑帧，不报错。
    故调用方必须先校验坐标在屏内，抓完再校验内容。
    """
    hdc_screen = user32.GetDC(0)
    if not hdc_screen:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)

    ok = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负值 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    lines = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf,
                            ctypes.byref(bi), DIB_RGB_COLORS)

    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)

    if not ok or lines == 0:
        return None
    return buf.raw, w, h


def region_on_screen(x, y, w, h):
    """抓帧前校验：坐标必须完整落在屏内（INV-17 的对策）。"""
    sw, sh = screen_size()
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= sw and y + h <= sh


# --- 输入 -------------------------------------------------------------


def click(x, y):
    """真实光标左键单击：SetCursorPos + SendInput（绝对归一化坐标）。

    走输入队列，不受 UIPI 限制（ADR 0001）。
    """
    import time

    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.08)

    sw, sh = screen_size()
    nx = int(x * 65535 / (sw - 1))
    ny = int(y * 65535 / (sh - 1))

    for flag in (MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
                 MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
        inp = INPUT()
        inp.type = 0
        inp.mi.dx = nx
        inp.mi.dy = ny
        inp.mi.dwFlags = flag
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.04)


# --- 进程 -------------------------------------------------------------


def process_image_path(pid):
    """取进程的可执行文件全路径，取不到返回 None。

    用于「杀之前先确认路径」（Q3 决策）。
    """
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(h)


def terminate_process(pid):
    """终止进程。返回 True/False，**只看返回值**。"""
    PROCESS_TERMINATE = 0x0001
    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not h:
        return False
    try:
        return bool(kernel32.TerminateProcess(h, 1))
    finally:
        kernel32.CloseHandle(h)


def list_processes(names=None):
    """按进程名列出 (name, pid, exe_path)。

    用 CreateToolhelp32Snapshot 而非 tasklist，避免子进程与编码问题。

    `names=None` ⇒ **不过滤**，列出全部进程。
    ⚠️ 为什么需要这个模式：`cleanup.confirm_exited` 要确认某个 pid 是否真的消失，
    而按名字筛会**漏看**仍存活的进程（ok-nte 第二层可能是 `python.exe`
    而非 `pythonw.exe`）⇒ 漏看就是误报「已退出」。
    确认存活/退出必须扫全量；按名字筛只适合**缩小范围**的可选优化。
    """
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    wanted = None if names is None else {n.lower() for n in names}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    out = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile
            if wanted is None or name.lower() in wanted:
                pid = entry.th32ProcessID
                out.append((name, pid, process_image_path(pid)))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out
