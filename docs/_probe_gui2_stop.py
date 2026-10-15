"""docs/_probe_gui2_stop.py — 单独查清楚 taskkill /T /F 之后进程到底还在不在

上一版自检里 "子进程确已终止" 失败，需要分辨两种可能：
  (a) 进程真的没被杀掉（产品 bug）；
  (b) 进程已被杀，但 Popen 还没回收，os.kill(pid,0) 仍能命中（测试写法问题）。

分辨方法：用 Popen.poll() / wait() 看**我们自己的**子进程状态，
并用 tasklist 查系统视角下该 pid 是否还存在。
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.runner import Runner  # noqa: E402

CF = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def in_tasklist(pid):
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=CF)
    return str(pid) in (r.stdout or "")


class Bus:
    def log(self, *a, **k):
        pass

    def node(self, *a, **k):
        pass

    def finished(self, *a, **k):
        pass

    def status(self, *a, **k):
        pass


print("=" * 70)
print("taskkill /T /F 之后的真实状态")
print("=" * 70)

r = Runner(Bus())
r.proc = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    creationflags=CF)
time.sleep(0.6)
pid = r.proc.pid
print(f"起子进程 pid={pid}")
print(f"  tasklist 命中（杀之前）: {in_tasklist(pid)}")
print(f"  Popen.poll()            : {r.proc.poll()}")

note = r.stop()
print(f"\nstop() -> {note}")
print(f"  Popen.poll()            : {r.proc.poll()}   (None=还在跑, 数字=已退出)")
print(f"  Popen.returncode        : {r.proc.returncode}")
print(f"  tasklist 命中（杀之后）  : {in_tasklist(pid)}")

print("\n结论：")
if r.proc.poll() is not None and not in_tasklist(pid):
    print("  ✅ 进程确实已终止。上一版自检用 os.kill(pid,0) 判断是错的写法 ——")
    print("     Windows 上 pid 在 Popen 回收前仍可能命中，这不是产品 bug。")
elif r.proc.poll() is not None and in_tasklist(pid):
    print("  ⚠️ Popen 已回收但 tasklist 仍命中 —— pid 可能被复用，需人工确认。")
else:
    print("  ❌ 进程仍在运行 —— 这是真实缺陷，stop() 没起作用。")
    sys.exit(1)
