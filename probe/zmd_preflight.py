r"""MaaEnd（zmd）测试前的只读体检 —— 3 点开跑前先跑它。

用途：把「现在能不能跑」判死，避免冷启动全链跑到节点 4 才发现 app 根本没起来。
**只读**：不启动、不点击、不改任何文件（日志只 stat 不读全文）。

用法：
    D:\WORKs\Anaconda\python.exe probe\zmd_preflight.py
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import programs, win32, window  # noqa: E402
from orchestrator import verdict  # noqa: E402

zmd = programs.get("zmd")
bad = []


def line(tag, ok, text):
    print(f"[{'OK ' if ok else 'BAD'}] {tag:<18} {text}")
    if not ok:
        bad.append(tag)


print("=== MaaEnd 测试前体检 ===")
print("时间:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

line("提权", win32.is_admin(), "is_admin()=%s" % win32.is_admin())
line("exe 存在", os.path.isfile(zmd.exe), zmd.exe)

procs = win32.list_processes(zmd.process_names)
mine = [p for p in procs if p[2] and zmd.owns_process(p[2])]
line("MaaEnd 未运行", not mine, "在跑: %s" % (mine or "无（冷启动全链就靠节点 2 拉起）"))

w = window.find_window(zmd)
line("当前无窗口", w is None, w and "%s hwnd=%s" % (w["title"], w["hwnd"]) or "无（预期，冷启动前）")

game = [p for p in win32.list_processes(["Endfield.exe", "Launcher.exe"])]
line("游戏/启动器未运行", not game, "在跑: %s" % ([p[0] for p in game] or "无"))

log = os.path.join(zmd.logdir, verdict.ZMD_LOG_NAME)
if os.path.isfile(log):
    st = os.stat(log)
    tail = ""
    with open(log, "rb") as fh:
        fh.seek(max(0, st.st_size - 4096))
        tail = fh.read().decode("utf-8", "replace").strip().splitlines()[-1:]
    line("日志可达", True, "%s  %d B  mtime=%s" % (
        verdict.ZMD_LOG_NAME, st.st_size,
        datetime.datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M:%S")))
    print("      最后一行:", (tail[0][:150] if tail else "<空>"))
else:
    line("日志可达", False, log)

print()
if bad:
    print("结论: 有 %d 项不满足 —— %s" % (len(bad), ", ".join(bad)))
    sys.exit(1)
print("结论: 可以开跑（冷启动全链不带 --no-launch，app 已在跑则带）")
