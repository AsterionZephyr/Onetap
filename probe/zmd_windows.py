# -*- coding: utf-8 -*-
"""探针：列出 MaaEnd 相关进程与窗口（只读）。"""
import ctypes, ctypes.wintypes as wt, os, sys, time

sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import win32

win32.ensure_dpi_aware()
print("screen:", win32.screen_size())

names = ["MaaEnd.exe", "Launcher.exe", "Endfield.exe", "go-service.exe", "cpp-algo.exe", "msedgewebview2.exe"]
for name, pid, exe in win32.list_processes(names):
    print(f"proc {name:24s} pid={pid:8d} exe={exe}")

print("\n--- all windows (title or class match) ---")
import re
pat = re.compile(r"MaaEnd|Endfield|Launcher|Hypergryph", re.I)

@ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
def cb(hwnd, _):
    title = win32.get_window_text(hwnd)
    cls = win32.get_class_name(hwnd)
    pid = win32.get_window_pid(hwnd)
    st = win32.window_state(hwnd)
    if title and pat.search(title) or (title and pid in PID_SET):
        print(f"hwnd={hwnd:<10} pid={pid:<8} cls={cls:<28} rect=({st['left']},{st['top']},{st['width']}x{st['height']}) iconic={st['iconic']} fg={st['foreground']} title={title!r}")
    return True

# MaaEnd 的 pid 集合 = MaaEnd.exe 及其子进程
PID_SET = {pid for name, pid, exe in win32.list_processes(None) if exe and "zmd" in exe.lower()}
print("zmd pids:", sorted(PID_SET))

# 直接按 pid 打印所有窗口（含无标题）
@ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
def cb2(hwnd, _):
    pid = win32.get_window_pid(hwnd)
    if pid in PID_SET:
        title = win32.get_window_text(hwnd)
        cls = win32.get_class_name(hwnd)
        st = win32.window_state(hwnd)
        print(f"  [zmd] hwnd={hwnd:<10} pid={pid:<8} cls={cls:<32} vis={st['visible']} rect=({st['left']},{st['top']},{st['width']}x{st['height']}) iconic={st['iconic']} title={title!r}")
    return True

print("\n--- windows owned by zmd processes ---")
win32.user32.EnumWindows(cb2, 0)

print("\n--- title regex MaaEnd ---")
for hwnd, pid, title, cls in win32.find_windows(r"(?i)MaaEnd"):
    st = win32.window_state(hwnd)
    print(f"hwnd={hwnd} pid={pid} cls={cls!r} rect={st['width']}x{st['height']}@{st['left']},{st['top']} title={title!r}")
