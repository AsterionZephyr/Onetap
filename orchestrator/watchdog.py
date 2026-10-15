"""orchestrator.watchdog — 整轮运行的时间上限与「到点强制收尾」

## 为什么需要它（用户要求，2026-10-16）

用户要求：「建议给 ok-ww 和 ok-nte 都设置一个超时时间，合理的取值是半小时，
**时间一到就手动关闭其窗口以及游戏**」。

各 step 内部**已经**有自己的超时（节点 4/5 各 300s，节点 8 兜底 1800s），
但它们覆盖不了三种情形：

1. **节点 8 之外的挂起**。节点 6 的 `--identity-timeout` 默认 120s，可节点 7
   置前台失败时会耗 `FOREGROUND_TRIES × FOREGROUND_INTERVAL`；更关键的是
   任何一步都可能因为**等待界面**而比预期慢得多。
2. **多个超时叠加**。节点 4 300s + 节点 5 300s + 节点 8 1800s = 最坏 40 分钟，
   而用户要的是**整轮**半小时。
3. **超时之后没人收尾**。这是最要命的：节点 8 判 TIMEOUT 后链条继续走到
   节点 9，节点 9 会杀**目标程序**的进程 —— 但它**从不杀游戏**
   （`cleanup.py` 的硬规则：游戏由目标程序自己负责）。于是「ok-nte 卡死但
   游戏还开着」这种现场（第 4 轮实测遇到过）会留下一个全屏游戏窗口，
   下一轮抓帧必然全黑。

所以本模块做两件 step 内部超时**做不到**的事：

    (a) **墙钟级**的总上限 —— 从开跑算起，与各 step 内部计时无关；
    (b) 到点**关窗口 + 关游戏** —— 而且是**显式**的收尾动作，
        不依赖目标程序是否愿意自己退。

## 设计取向：到点之后不抛异常，而是「执行一个收尾动作」

`Deadline.expired()` 只回答「超了没有」；真正的收尾由 `force_close()` 做。
主控在每节之间检查一次 —— 这样既不需要给每个 step 加参数，
也不会在某一节**正跑着**的时候把它拦腰砍断（那样会留下半点击状态）。

    ⚠️ 粒度是「节」而不是「秒」：若节点 8 自己挂住不返回，主控也要等它。
    故节点 8 的 `--total-timeout` **必须**由主控按总上限一起设小，
    两者是互补的（见 `main.py` 的 `--total-timeout` 推导）。

## 关窗口与关进程的次序（重要）

先**关窗口**（`WM_CLOSE`，给程序一个体面退出的机会），等一小会儿，
再**杀进程**。理由：目标程序在自我收尾时会自己把游戏杀掉并写日志；
直接杀进程会跳过这一步，留下孤儿游戏进程。只有在关窗口无效时才动刀。

## 不能碰的东西

本模块只动两类进程：**目标程序自己的**（按 `process_prefix` 判定）
与**它对应的游戏**（按 `game_names` 进程名判定）。绝不按名字泛杀 ——
本机同时有 searxng 的 pythonw、Anaconda 的 pythonw/python（实测），
按名字扫会误杀（FAULT #19 的教训）。
"""

import time

from . import cleanup as cleanup_mod
from . import programs as programs_mod
from . import win32
from . import window

# 关窗口后等它自己退出的宽限时间（秒）。目标程序收到 WM_CLOSE 后要写日志、
# 杀游戏，实测需要几秒；给 10 秒足够，再久就该动刀了。
GRACEFUL_SECONDS = 10.0

# 杀完之后等进程从进程表消失的上限（秒）。FAULT #13 的同一教训：
# kill 成功到进程表更新有延迟，立刻枚举会误报「仍存活」。
REAP_SECONDS = 8.0


class Deadline:
    """整轮运行的墙钟上限。

    用法：

        dl = Deadline(1800, log=log)     # 30 分钟
        dl.begin()                       # 开始计时（在干活之前调）
        ...
        if dl.expired():                 # 每节之间查
            dl.describe()
    """

    def __init__(self, seconds, log=None):
        self.seconds = float(seconds)
        self.log = log
        self.t0 = None

    def begin(self, t0=None):
        self.t0 = time.time() if t0 is None else t0
        return self

    def elapsed(self):
        if self.t0 is None:
            return 0.0
        return time.time() - self.t0

    def remaining(self):
        if self.t0 is None:
            return self.seconds
        return max(0.0, self.seconds - self.elapsed())

    def expired(self):
        if self.t0 is None or self.seconds <= 0:
            return False
        return self.elapsed() >= self.seconds

    def describe(self):
        return (f"已用 {self.elapsed():.0f}s / 上限 {self.seconds:.0f}s"
                f"（余 {self.remaining():.0f}s）")


def game_windows(program):
    """找出目标程序对应游戏的顶层窗口，返回 [(hwnd, pid, title, class), ...]。

    ⚠️ 判据是**进程名**而非窗口标题：实测两个游戏的主窗口标题都不稳定
    （鸣潮实测 `'鸣潮  '` 带尾随空格；ok-nte 的 HTGame 窗口标题可能为空）。
    故先把窗口按 pid 归到进程，再看 pid 的进程名是否在 program.game_names 里。

    ⚠️ 不能用 `win32.find_windows(".*")` —— 它内部有 `if title and ...`，
    **会跳过标题为空的窗口**（`win32.py:219`），而游戏窗口标题恰恰可能为空。
    这里直接枚举全部顶层窗口，逐个按 pid 判归属。
    """
    import os

    prog = programs_mod.get(program)
    if not prog.game_names:
        return []
    wanted = {n.lower() for n in prog.game_names}

    out = []

    @win32.ctypes.WINFUNCTYPE(win32.wt.BOOL, win32.wt.HWND, win32.wt.LPARAM)
    def cb(hwnd, _):
        pid = win32.get_window_pid(hwnd)
        if pid:
            exe = win32.process_image_path(pid)
            if exe and os.path.basename(exe).lower() in wanted:
                out.append((hwnd, pid, win32.get_window_text(hwnd),
                            win32.get_class_name(hwnd)))
        return True

    win32.user32.EnumWindows(cb, 0)
    return out


def game_processes(program):
    """目标程序对应游戏的进程（按进程名），返回 [(name, pid, exe), ...]。"""
    prog = programs_mod.get(program)
    if not prog.game_names:
        return []
    return list(win32.list_processes(prog.game_names))


def close_window(hwnd):
    """给窗口发 WM_CLOSE（体面退出）。返回是否发送成功。"""
    WM_CLOSE = 0x0010
    try:
        return bool(win32.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    except Exception:
        return False


def force_close(program=None, reason="timeout", log=None, dry_run=False,
                close_game=True):
    """超时收尾：关目标程序窗口 → 关游戏窗口 → 必要时杀进程。

    返回一份结果 dict，供上层写进 state.json —— **必须落盘**，
    否则「超时后被强制收尾」这件事会变成静默行为。
    """
    prog = programs_mod.get(program)
    say = log or (lambda *_a: None)
    res = {
        "reason": reason,
        "closed_windows": [],
        "closed_game_windows": [],
        "target": prog.key,
        "dry_run": bool(dry_run),
    }

    say("")
    say("=" * 74)
    say(f"[超时收尾] {prog.display} —— 整轮时间上限到了（{reason}）")
    say("  按用户裁定：到点手动关闭其窗口以及游戏")
    say("=" * 74)

    # --- 1. 目标程序的窗口 ------------------------------------------------
    w = window.find_window(prog, require_ready=False)
    if w:
        say(f"  关闭 {prog.display} 窗口 hwnd={w['hwnd']} 标题={w['title']!r}")
        if not dry_run:
            if close_window(w["hwnd"]):
                res["closed_windows"].append(w["hwnd"])
                time.sleep(1.0)
            else:
                say("    [警告] WM_CLOSE 发送失败，稍后按进程处理")
    else:
        say(f"  {prog.display} 无窗口可关")

    # --- 2. 游戏的窗口（先关窗，让它自己收尾）-----------------------------
    gw = game_windows(prog)
    if gw and close_game:
        for hwnd, pid, title, cls in gw:
            say(f"  关闭游戏窗口 hwnd={hwnd} pid={pid} 标题={title!r} 类={cls}")
            if not dry_run and close_window(hwnd):
                res["closed_game_windows"].append(hwnd)
    elif gw:
        say(f"  游戏窗口 {len(gw)} 个（--keep-game 要求保留，不关）")
    else:
        say("  游戏无窗口可关")

    if dry_run:
        say("  [DRY RUN] 不终止任何进程")
        return res

    # --- 3. 宽限：给它们自己退出的时间 ------------------------------------
    if res["closed_windows"] or res["closed_game_windows"]:
        say(f"  宽限 {GRACEFUL_SECONDS:.0f}s，等它们自行退出…")
        time.sleep(GRACEFUL_SECONDS)

    # --- 4. 兜底杀进程：目标程序 ------------------------------------------
    alive = window.running(prog)
    if alive:
        say(f"  {prog.display} 仍有 {len(alive)} 个进程存活，执行终止")
        r = cleanup_mod.run_cleanup(prog.root_dir, program=prog,
                                    reason=reason, log=log, dry_run=False)
        res["killed_target"] = r["killed"]
        _reap(prog, log=log)
    else:
        say(f"  {prog.display} 进程已全部退出")
        res["killed_target"] = []

    # --- 5. 兜底杀进程：游戏 ----------------------------------------------
    if close_game:
        gp = game_processes(prog)
        if gp:
            say(f"  游戏仍有 {len(gp)} 个进程存活，执行终止")
            killed = []
            for name, pid, exe in gp:
                if win32.terminate_process(pid):
                    say(f"    已终止 {name} pid={pid}")
                    killed.append((name, pid, exe))
                else:
                    say(f"    终止失败 {name} pid={pid}")
            res["killed_game"] = killed
            _reap_names([n for n, _, _ in gp], log=log)
        else:
            say("  游戏进程已全部退出")
            res["killed_game"] = []

    say("=" * 74)
    say("[超时收尾] 完成")
    say("=" * 74)
    return res


def _reap(prog, log=None):
    """等目标程序进程真正消失（FAULT #13 的同一教训）。"""
    deadline = time.time() + REAP_SECONDS
    while time.time() < deadline:
        if not window.running(prog):
            if log:
                log(f"  [OK] 进程已在 {REAP_SECONDS:.0f}s 内全部退出")
            return True
        time.sleep(0.2)
    still = window.running(prog)
    if log and still:
        log(f"  [!!] 等待 {REAP_SECONDS:.0f}s 后仍有 {[(n, p) for n, p, _ in still]} 存活")
    return not still


def _reap_names(names, log=None):
    """按进程名等进程真正消失。"""
    deadline = time.time() + REAP_SECONDS
    while time.time() < deadline:
        if not win32.list_processes(names):
            if log:
                log(f"  [OK] 游戏进程已在 {REAP_SECONDS:.0f}s 内全部退出")
            return True
        time.sleep(0.2)
    still = win32.list_processes(names)
    if log and still:
        log(f"  [!!] 等待 {REAP_SECONDS:.0f}s 后游戏仍有 {[(n, p) for n, p, _ in still]} 存活")
    return not still


def survey(program=None, log=None):
    """只读：报告目标程序与游戏的现状（不关、不杀）。"""
    prog = programs_mod.get(program)
    say = log or print
    say(f"[巡视] {prog.display}（{prog.key}）")
    r = window.running(prog)
    say(f"  目标进程 {len(r)} 个：{[(n, p) for n, p, _ in r]}")
    w = window.find_window(prog, require_ready=False)
    say(f"  目标窗口：{w['hwnd'] if w else None}"
        + (f" 标题={w['title']!r}" if w else ""))
    gp = game_processes(prog)
    say(f"  游戏进程 {len(gp)} 个：{[(n, p) for n, p, _ in gp]}")
    gw = game_windows(prog)
    say(f"  游戏窗口 {len(gw)} 个：{[(h, t) for h, _, t, _ in gw]}")
    return {"target_processes": r, "target_window": w,
            "game_processes": gp, "game_windows": gw}
