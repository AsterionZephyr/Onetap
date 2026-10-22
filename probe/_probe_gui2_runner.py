"""probe/_probe_gui2_runner.py — 验证 gui.runner 真能驱动 steps/main.py

不弹窗、不启动 ok-ww。用 `--list`（只打印链条，不执行）验证：
  子进程起得来、stdout 收得到、退出码读得到、整树终止可用。

跑法：
    & "D:\\WORKs\\Anaconda\\python.exe" -X utf8 probe\\_probe_gui2_runner.py
"""

import json
import os
import sys
import threading
import time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui import chain                      # noqa: E402
from gui.runner import Runner, StateWatcher  # noqa: E402

FAIL = []


def _in_tasklist(pid):
    """系统视角下该 pid 是否仍存在。"""
    import subprocess
    r = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return str(pid) in (r.stdout or "")


def check(name, ok, detail=""):
    print(f"  {'[OK]  ' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


def _state_files(run_dir):
    """该运行目录下的全部 state.json（根 + 各子目录，与 StateWatcher._scan 一致）。"""
    out = []
    if not run_dir or not os.path.isdir(run_dir):
        return out
    p = os.path.join(run_dir, "state.json")
    if os.path.isfile(p):
        out.append(p)
    for name in sorted(os.listdir(run_dir)):
        sub = os.path.join(run_dir, name)
        q = os.path.join(sub, "state.json")
        if os.path.isdir(sub) and os.path.isfile(q):
            out.append(q)
    return out


def _max_steps(run_dir):
    """该目录里各 state.json 的最多节点数（挑夹具用）。"""
    best = 0
    for p in _state_files(run_dir):
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            continue
        best = max(best, len(raw.get("steps") or {}))
    return best


def _find_run_dir_with_state(limit=40, min_nodes=1):
    """从新到旧找一个真含 state.json 的运行目录。

    最新目录可能刚建、还没写 state.json（或是个纯串联根目录），
    也可能只有一两个节点的短跑（--only 1 的干跑）——
    所以既不能只用 latest_run_dir()，也要能按「至少几个节点」筛。
    """
    root = chain.default_run_root()
    try:
        names = sorted(os.listdir(root), reverse=True)
    except OSError:
        return None
    for name in names[:limit]:
        d = os.path.join(root, name)
        if os.path.isdir(d) and _state_files(d) and _max_steps(d) >= min_nodes:
            return d
    return None


class Bus:
    """收集事件，代替 GUI 主线程。"""

    def __init__(self):
        self.lines = []
        self.lock = threading.Lock()

    def log(self, msg, kind=None):
        with self.lock:
            self.lines.append(msg)

    def node(self, *a, **k):
        pass

    def finished(self, *a, **k):
        pass

    def status(self, *a, **k):
        pass


print("=" * 74)
print("gui.runner 驱动 steps/main.py 自检")
print("=" * 74)

bus = Bus()
r = Runner(bus)

# ---------------------------------------------------------------- 1
print("\n1. 起子进程跑 `main.py --list`")
r.start(sys.executable, ["--list"])
code = r.stream_output()
time.sleep(0.2)

text = "\n".join(bus.lines)
check("退出码为 0", code == 0, f"code={code}")
check("收到了输出", len(bus.lines) > 0, f"{len(bus.lines)} 行")
check("链条里含节点 1", "提权检查" in text)
check("链条里含节点 9", "退出与清理" in text)
check("说明无节点 3", "无节点 3" in text or "跨过第一层" in text)
check("子进程已结束", not r.is_running())

# ---------------------------------------------------------------- 2
print("\n2. `--only` 参数能透传（用一个必然不存在的节点验证解析）")
bus2 = Bus()
r2 = Runner(bus2)
r2.start(sys.executable, ["--only", "99"])
code2 = r2.stream_output()
t2 = "\n".join(bus2.lines)
check("非法节点被拒绝", code2 != 0, f"code={code2}")
check("给出了可读错误", "不在链条中" in t2, t2.strip().splitlines()[-1][:70]
      if t2.strip() else "(无输出)")

# ---------------------------------------------------------------- 3
print("\n3. 停止：整树终止")
bus3 = Bus()
r3 = Runner(bus3)
# 起一个会跑一会儿的任务：main.py 的 --list 太快，改用 python -c 挂起
import subprocess
env = dict(os.environ)
env["PYTHONUNBUFFERED"] = "1"
r3.proc = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
time.sleep(0.5)
check("子进程在跑", r3.is_running())
pid = r3.proc.pid
note = r3.stop()
check("stop() 报告了结果", bool(note), note)

# ⚠️ 判据用 Popen.poll()，**不要**用 os.kill(pid, 0)。
#    Windows 上 pid 在 Popen 回收前仍可能命中，那是测试写法的问题，
#    不是"没杀掉"（见 probe/_probe_gui2_stop.py 的对照）。
deadline = time.time() + 5
while time.time() < deadline and r3.proc.poll() is None:
    time.sleep(0.1)
check("子进程确已终止", r3.proc.poll() is not None,
      f"pid={pid} returncode={r3.proc.returncode}")
check("is_running() 变为 False", not r3.is_running())
check("tasklist 里已无此 pid", not _in_tasklist(pid), f"pid={pid}")

# ---------------------------------------------------------------- 4
# StateWatcher 现在扫「根目录 + 各子目录」的 state.json（串联时是
# <root>/ww/ 与 <root>/nte/ 各一份），poll() 返回 {target: raw}、推送带 target。
print("\n4. StateWatcher 读真实的 state.json")
# 夹具要求：至少 3 个节点（最新目录常常是 --only 1 的短跑，只有 1 个节点）
rd = chain.latest_run_dir()
if rd and (not _state_files(rd) or _max_steps(rd) < 3):
    if _state_files(rd):
        print(f"  （最新目录只有 {_max_steps(rd)} 个节点：{chain.rel(rd)}，往前找）")
    else:
        print(f"  （最新目录里没有 state.json：{chain.rel(rd)}，往前找）")
    rd = _find_run_dir_with_state(min_nodes=3)
check("找到了历史运行目录", rd is not None, chain.rel(rd) if rd else "无")
if rd:
    bus4 = Bus()
    seen = []

    class B4(Bus):
        def node(self, target, sid, name, status, note=None, elapsed=None):
            seen.append((target, sid, status))

    w = StateWatcher(B4(), rd)
    raws = w.poll()
    check("读出了 state.json", bool(raws), f"{len(raws)} 份")
    if raws:
        target, raw = next(iter(raws.items()))
        n = len(raw.get("steps") or {})
        check("含多个节点记录", n >= 3, f"target={target} {n} 个节点")
        check("首次轮询推送了状态", len(seen) > 0, f"{len(seen)} 条")
        check("推送都带 target",
              all(t is not None for t, _s, _st in seen),
              f"targets={sorted({str(t) for t, _s, _st in seen})}")
        # 第二次轮询 mtime 不变，应当不再推送（去重生效）
        seen.clear()
        raws2 = w.poll()
        check("mtime 未变时不重复推送", raws2 == {} and len(seen) == 0,
              f"raws2={raws2} 推送={len(seen)} 条")

print("\n" + "=" * 74)
if FAIL:
    print(f"失败 {len(FAIL)} 项：")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过。")
