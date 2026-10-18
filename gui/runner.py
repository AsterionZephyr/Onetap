"""gui.runner — 子进程驱动 steps/main.py，并轮询 state.json

**为什么是子进程，而不是像旧骨架那样同进程开线程**（[orchestrator/gui.py]
(../orchestrator/gui.py) 的做法）：

  1. `steps/main.py` **本身就是子进程模型** —— 它用 `subprocess.run` 调用各节点
     （[main.py:235](../orchestrator/steps/main.py#L235)）。节点间只通过
     `state.json` 通信，不共享内存，所以从外面再包一层进程没有任何损失。
  2. **停止才可能**。旧骨架的"停止"只能弹一个"无法中断"的对话框
     （[gui.py:391](../orchestrator/gui.py#L391)），因为同进程里的同步循环
     没法安全打断。子进程可以用 `taskkill /T` 整树终止。
  3. **GUI 与编排解耦**。GUI 不再 import 编排代码，编排炸了 GUI 还活着。

⚠️ **停止必须带 `/T`**：`main.py` 起节点是父子关系，只杀主控会留下
   孤儿节点进程继续**操作真实鼠标**。这不是洁癖 —— 是防止 GUI 显示"已停止"
   而屏幕上鼠标还在自己动。

状态来源是 `state.json`（不是解析日志）：`RunState.begin()` 先写
`status: "running"` 并落盘（[context.py:220](../orchestrator/steps/context.py#L220)），
`finish()` 再覆盖，所以轮询它能拿到**准确**的当前节点。
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

from . import chain

# 轮询间隔：state.json 是小文件，读一次约 0.1ms，所以可以取得比较密。
# 80ms 与旧骨架的事件轮询同频，肉眼已经"实时"。
POLL_MS = 80


class Runner:
    """管理一次编排运行：起子进程、读状态、终止进程树。

    所有回调（on_log / on_state / on_finished）都在**调用方的线程**里触发 ——
    本类自己不建线程，线程由 app 层负责。它只把结果塞进 queue。
    """

    def __init__(self, bus):
        self.bus = bus
        self.proc = None
        self.run_dir = None
        self._stop_flag = threading.Event()
        self._reader = None

    # ------------------------------------------------------------ 生命周期

    def start(self, python, args, run_dir=None, cwd=None):
        """起一个 `python -m orchestrator.steps.main <args...>` 子进程。

        python: 解释器绝对路径（默认与 GUI 同一个解释器）
        args:   传给 main.py 的参数列表
        run_dir: 若指定，则运行目录已知（GUI 自己建的），否则从 stdout 里认。
        """
        cmd = [python, "-m", "orchestrator.steps.main"] + list(args)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"     # 中文日志不因管道编码变乱码
        env["PYTHONUNBUFFERED"] = "1"         # 让日志**实时**出来，而不是攒着

        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            # 不弹黑框；子进程自己的日志我们通过管道收
            creation = subprocess.CREATE_NO_WINDOW

        self._stop_flag.clear()
        self.run_dir = run_dir
        self.proc = subprocess.Popen(
            cmd, cwd=cwd or chain.ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=creation,
        )
        self.bus.log(f"$ {' '.join(cmd)}", kind="cmd")
        return self.proc

    def stream_output(self):
        """在**当前线程**里把子进程 stdout 逐行读出来，直到退出。

        调用方应当把它放进一个 worker 线程。返回退出码。
        """
        assert self.proc is not None, "先调 start()"
        try:
            for line in self.proc.stdout:
                self.bus.log(line.rstrip("\n"))
        except (ValueError, OSError):
            pass
        finally:
            try:
                self.proc.stdout.close()
            except (OSError, AttributeError):
                pass

        code = self.proc.wait()
        return code

    def stop(self, timeout=6.0):
        """整树终止。返回一句人能看懂的说明。

        `taskkill /T` 杀掉整个进程树 —— 主控 + 当前正在跑的节点脚本。
        `/F` 是强制的：节点脚本在抓帧/等待循环里不响应温和的 terminate。
        """
        if not self.proc or self.proc.poll() is not None:
            return "没有在运行的编排"

        pid = self.proc.pid
        self._stop_flag.set()
        detail = []
        try:
            r = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                timeout=timeout)
            if r.returncode == 0:
                detail.append(f"已终止进程树 (pid {pid})")
            else:
                # taskkill 失败时退回到只杀主控，并如实说明可能留下孤儿
                self.proc.kill()
                detail.append(f"taskkill 返回 {r.returncode}，已退回到 kill 主控；"
                              f"可能有孤儿节点进程")
        except (subprocess.TimeoutExpired, OSError) as e:
            try:
                self.proc.kill()
            except OSError:
                pass
            detail.append(f"终止异常（{type(e).__name__}），已 kill 主控")

        # 确认窗口/进程真的没了
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            detail.append("进程仍未退出")
        return "；".join(detail)

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None


# ===========================================================================
# state.json 轮询
# ===========================================================================

class StateWatcher:
    """轮询运行目录下的 state.json，把变化推给 GUI。

    **一个运行目录里可能有多份 state.json**：串联（`--target ww,nte`）时主控
    建一个根目录，每轮程序在自己的子目录里跑 —— `<root>/ww/state.json`、
    `<root>/nte/state.json`；单程序时就是 `<root>/state.json`（`--resume` 也是）。
    所以这里扫的是"根目录 + 各子目录"，每份各自比 mtime、各自去重。

    只做"读文件 + 比较"，不解释业务。任何异常都吞掉 —— state.json 在
    写入瞬间仍可能被读到半个文件（context.py 用 os.replace 原子替换，
    但新目录出现/消失的竞态仍可能发生）。
    """

    def __init__(self, bus, run_dir):
        self.bus = bus
        self.set_run_dir(run_dir)

    def set_run_dir(self, run_dir):
        self.run_dir = os.path.abspath(run_dir) if run_dir else None
        self._mtimes = {}     # path -> mtime（按路径记，不按 target 记）
        self._steps = {}      # path -> {sid: status}

    def _scan(self):
        """返回 [(目标提示, state.json 路径)]。目标提示可能是 None。"""
        found = []
        if not self.run_dir or not os.path.isdir(self.run_dir):
            return found
        root_state = os.path.join(self.run_dir, "state.json")
        if os.path.isfile(root_state):
            found.append((None, root_state))
        try:
            names = sorted(os.listdir(self.run_dir))
        except OSError:
            return found
        for name in names:
            sub = os.path.join(self.run_dir, name)
            if not os.path.isdir(sub):
                continue
            p = os.path.join(sub, "state.json")
            if os.path.isfile(p):
                found.append((name, p))
        return found

    def poll(self):
        """读一轮所有 state.json。

        返回 `{target: raw}`（target = state.json 里的 `program`，缺失时退回
        子目录名；单程序运行也可能是 None）。**没有变化时返回 `{}`** ——
        调用方不要用 `if raw:` 以外的方式判断"读到了"。
        """
        out = {}
        for hint, path in self._scan():
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if self._mtimes.get(path) == mtime:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError):
                continue
            self._mtimes[path] = mtime
            target = raw.get("program") or hint
            out[target] = raw
            seen = self._steps.setdefault(path, {})
            for sid, rec in (raw.get("steps") or {}).items():
                status = rec.get("status")
                if seen.get(sid) == status:
                    continue
                seen[sid] = status
                self.bus.node(target, sid, rec.get("name", ""), status,
                              note=(rec.get("notes") or [None])[-1],
                              elapsed=rec.get("elapsed"))
        return out


def discover_run_dir_from_line(line):
    """从主控日志里认出运行目录（主控会打印 `运行目录 <path>`）。

    仅作为兜底：正常运行由 GUI 自己指定 --run-dir。
    """
    marker = "运行目录 "
    if marker in line:
        cand = line.split(marker, 1)[1].strip()
        if os.path.isdir(cand):
            return cand
    return None
