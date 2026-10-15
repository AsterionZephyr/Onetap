"""steps.context — 断点式拆分：各 step 之间唯一的交接面

**目的**：把 `orchestrator/orchestrator.py` 里那条一气呵成的链条，按 README §5
的节点位置切成若干份**独立可单跑**的脚本。任意一环出错，都能只打开那一份代码
修改并单独重跑，不必碰其他代码块。

三条设计约束（这是"断点"能成立的前提）：

  1. **单一交接面**：step 之间**只**通过 `<run-dir>/state.json` 与若干 PNG 文件
     通信，不共享 Python 对象、不共享内存。任何一个 step 换个进程跑，结果一样。
  2. **每个 step 可单跑**：`python -m orchestrator.steps.step6_first_frame --run-dir <dir>`
     读上一节写下的 state.json，自己做完这一节，再写回 state.json。
     **不要求前面的 step 在同一个进程里跑过**。
  3. **起点可注入**：`--adopt-hwnd` / `--adopt-frame` 允许你把"上一节的结果"
     手工塞进来（例如程序已经在跑、或已有一张落盘的帧），从而**跳过**前面的节点
     直接调试某一节。

`state.json` 的形状（每一步只增不改自己那一段，见 `RunState`）：

    {
      "run_dir":     "...",
      "started_at":  "2026-01-01 12:00:00",
      "dry_run":     false,
      "steps": {
        "1": {"name":"check_admin", "status":"ok", "started_at":..., "elapsed":0.1,
              "data": {...}, "shots": [...]},
        ...
      },
      "hwnd":   8196624,          # 窗口句柄（节点 4 之后有效）
      "pid":    4076,
      "frame":  {"path":".../001-first-frame.png", "width":1823, "height":1000,
                 "rect":[360,44,2183,1044]},
      "result": "completed"       # 节点 8/9 之后有效
    }

**为什么不把 hwnd 缓存在进程里**：INV-14 明确要求"hwnd 不缓存，每次重新发现"
（每次运行都不同，实测出现过六个值）。所以 state.json 里的 hwnd 只是**记录**，
每个真正要用它的 step 都会先用标题正则**重新发现**一次并以新值覆盖。
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime

# 仓库根：orchestrator/steps/context.py -> 上溯三层
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ROOT = os.path.dirname(PKG)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_RUN_ROOT = os.path.join(ROOT, "logs", "runs")


# ------------------------------------------------------------------ 日志


class Log:
    """同时写 stdout 与 `<run-dir>/chain.log` 的日志。

    文件一律 UTF-8。踩过的坑：PowerShell 管道下 stdout 的编码会把中文变成乱码，
    故 stdout 与文件**分开处理编码**，文件不依赖 stdout 的设置。
    """

    def __init__(self, path=None):
        self.path = path
        self.fh = None
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.fh = open(path, "a", encoding="utf-8", newline="\n")

    def __call__(self, msg=""):
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("utf-8", "replace").decode("ascii", "replace"),
                  flush=True)
        if self.fh:
            self.fh.write(str(msg) + "\n")
            self.fh.flush()

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None


def read_text(path):
    """读文本，编码不确定时依次尝试 utf-8 / gbk。"""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ------------------------------------------------------------- 运行目录


def new_run_dir(prefix="run", root=None):
    """建一个带时间戳的运行目录，返回其绝对路径。"""
    root = root or DEFAULT_RUN_ROOT
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(root, f"{prefix}-{stamp}")
    os.makedirs(os.path.join(path, "shots"), exist_ok=True)
    return path


def latest_run_dir(root=None):
    """最近一次运行目录（供 --run-dir 省略时使用）。"""
    root = root or DEFAULT_RUN_ROOT
    if not os.path.isdir(root):
        return None
    cands = [os.path.join(root, d) for d in os.listdir(root)
             if os.path.isdir(os.path.join(root, d))]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


# -------------------------------------------------------------- 状态读写


class StateError(Exception):
    """状态文件缺失或形状不对 —— 说明「上一节没跑」或「跑的不是同一条链」。"""


class RunState:
    """`state.json` 的读写门面。

    每个 step 的典型用法：

        st = RunState.load(args.run_dir)      # 读上一节的结果
        st.begin("6", "first_frame", log)
        ...
        st.set("hwnd", hwnd)
        st.finish("6", "ok", {"score": 0.98}, log)
    """

    def __init__(self, run_dir, raw=None):
        self.run_dir = os.path.abspath(run_dir)
        self.path = os.path.join(self.run_dir, "state.json")
        self.raw = raw if raw is not None else {
            "run_dir": self.run_dir,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run": False,
            "steps": {},
        }

    # --- 构造 ---------------------------------------------------------

    @classmethod
    def create(cls, run_dir, dry_run=False):
        os.makedirs(os.path.join(run_dir, "shots"), exist_ok=True)
        st = cls(run_dir)
        st.raw["dry_run"] = bool(dry_run)
        st.save()
        return st

    @classmethod
    def load(cls, run_dir, must_exist=True):
        run_dir = os.path.abspath(run_dir)
        path = os.path.join(run_dir, "state.json")
        if not os.path.isfile(path):
            if must_exist:
                raise StateError(
                    f"找不到状态文件：{path}\n"
                    f"  => 这条链还没开始。先跑 step1，或用 --run-dir 指向已存在的运行目录。")
            return cls.create(run_dir)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls(run_dir, raw)

    # --- 基本访问 -----------------------------------------------------

    def __getitem__(self, key):
        return self.raw.get(key)

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def set(self, key, value):
        self.raw[key] = value
        return value

    @property
    def dry_run(self):
        return bool(self.raw.get("dry_run"))

    @property
    def shots_dir(self):
        return os.path.join(self.run_dir, "shots")

    def shot_path(self, tag):
        """给一张待落盘的图起名：`<序号>-<tag>.png`，序号按已记录张数递增。"""
        n = sum(len(s.get("shots", [])) for s in self.raw["steps"].values()) + 1
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(tag))
        return os.path.join(self.shots_dir, f"{n:03d}-{safe}.png")

    # --- step 生命周期 ------------------------------------------------

    def begin(self, step_id, name, log=None):
        rec = self.raw["steps"].setdefault(str(step_id), {})
        rec.update({
            "name": name,
            "status": "running",
            "started_at": datetime.now().strftime("%H:%M:%S"),
            "host": os.getpid(),
        })
        rec.setdefault("shots", [])
        rec.setdefault("data", {})
        self.save()
        if log:
            log(f"\n{'=' * 74}")
            log(f"[节点 {step_id}] {name}   （run-dir {self.run_dir}）")
            log(f"{'=' * 74}")
        return rec

    def finish(self, step_id, status, data=None, log=None, note=None):
        rec = self.raw["steps"].setdefault(str(step_id), {})
        rec["status"] = status
        rec["finished_at"] = datetime.now().strftime("%H:%M:%S")
        if "started_at" in rec:
            # 跨进程/跨天也能算：用时间戳差
            try:
                t0 = datetime.strptime(
                    f"{datetime.now():%Y-%m-%d} {rec['started_at']}", "%Y-%m-%d %H:%M:%S")
                rec["elapsed"] = round((datetime.now() - t0).total_seconds(), 1)
            except ValueError:
                pass
        if data:
            rec.setdefault("data", {}).update(data)
        if note:
            rec.setdefault("notes", []).append(note)
        self.save()
        if log:
            mark = {"ok": "OK", "failed": "FAILED", "skipped": "SKIPPED",
                    "timeout": "TIMEOUT"}.get(status, status.upper())
            log(f"[节点 {step_id}] -> {mark}"
                + (f"   {note}" if note else ""))
        return rec

    def add_shot(self, step_id, path):
        rec = self.raw["steps"].setdefault(str(step_id), {})
        rel = os.path.relpath(path, self.run_dir).replace("\\", "/")
        rec.setdefault("shots", []).append(rel)
        self.save()
        return rel

    def save(self):
        os.makedirs(self.run_dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # --- 链条健康度 ---------------------------------------------------

    def step_status(self, step_id):
        return self.raw["steps"].get(str(step_id), {}).get("status")

    def require(self, step_id, what):
        """要求某个节点已经跑过（ok 或按参数 skipped），否则报错说明缺哪一节。"""
        s = self.step_status(step_id)
        if s not in ("ok", "skipped"):
            raise StateError(
                f"节点 {step_id} 尚未成功完成（当前状态 {s!r}），无法取得「{what}」。\n"
                f"  => 先跑 step{step_id}，或用对应的 --adopt-* 参数手工注入。")
        return self.raw["steps"][str(step_id)].get("data", {})

    def summary(self):
        lines = []
        for sid in sorted(self.raw["steps"], key=lambda s: (len(s), s)):
            r = self.raw["steps"][sid]
            mark = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]",
                    "timeout": "[TIME]", "running": "[....]"}.get(
                r.get("status"), "[?]   ")
            el = r.get("elapsed")
            el = f"{el:6.1f}s" if isinstance(el, (int, float)) else "      "
            lines.append(f"  {mark} 节点 {sid:>2}  {r.get('name',''):22s} {el}"
                         + (f"  {r.get('notes', [''])[-1]}" if r.get("notes") else ""))
        return "\n".join(lines)


# ------------------------------------------------------- 窗口/钩子的再发现


def rediscover_hwnd(state, log=None):
    """按标题正则**重新发现**窗口持有者（INV-14：hwnd 绝不缓存）。

    节点 4 之后每个要用窗口的 step 都调用它，而不是相信 state.json 里的旧值。
    回退顺序：Qt 窗口 -> 任意非 Tauri 窗口 -> state.json 里的记录值。
    """
    from .. import window
    info = window.find_okww_window()
    if info:
        if log and state.get("hwnd") not in (None, info["hwnd"]):
            log(f"  hwnd 重新发现：{state.get('hwnd')} -> {info['hwnd']}（INV-14）")
        state.set("hwnd", info["hwnd"])
        state.set("pid", info["pid"])
        return info["hwnd"]
    old = state.get("hwnd")
    if log:
        log(f"  [警告] 标题正则未发现窗口，回退到 state.json 记录的 hwnd={old}")
    return old


def require_hwnd(state, log=None):
    hwnd = rediscover_hwnd(state, log=log)
    if not hwnd:
        raise StateError(
            "没有可用的窗口句柄：标题正则没发现 ok-ww 窗口，state.json 里也没有记录。\n"
            "  => 先跑 step4（等待第二层），或用 --adopt-hwnd 手工指定。")
    return hwnd


# ------------------------------------------------------------ 命令行共用


def add_common_args(ap):
    """给每个 step 脚本装上统一的参数。"""
    ap.add_argument("--run-dir", default=None,
                    help="运行目录（存放 state.json 与抓图）。省略时取最近一次运行。")
    ap.add_argument("--dry-run", action="store_true",
                    help="只做校验与定位，不点击、不杀进程")
    ap.add_argument("--new-run", action="store_true",
                    help="强制新建一个运行目录（否则沿用 --run-dir / 最近一次）")
    return ap


def resolve_run_dir(args, log=None, create=False):
    """把 --run-dir / --new-run / 最近一次 解析成一个确定的目录。

    用 getattr 读参数：主控（main.py）有自己的参数集，没有 --new-run。
    """
    if getattr(args, "new_run", False) or create:
        d = new_run_dir()
        if log:
            log(f"[运行目录] 新建 {d}")
        return d
    rd = getattr(args, "run_dir", None)
    if rd:
        return os.path.abspath(rd)
    d = latest_run_dir()
    if d:
        if log:
            log(f"[运行目录] 沿用最近一次 {d}")
        return d
    d = new_run_dir()
    if log:
        log(f"[运行目录] 无历史运行，新建 {d}")
    return d


def make_log(run_dir, step_id):
    """每个 step 一份自己的日志文件，便于单独排查。"""
    os.makedirs(run_dir, exist_ok=True)
    return Log(os.path.join(run_dir, f"step{step_id}.log"))


def run_step(step_id, name, body, extra_args=None):
    """step 脚本的统一外壳。

    body(args, state, log) -> (status, data, note)
    status 取 "ok" / "failed" / "skipped" / "timeout"；非 "ok" 时退出码非 0。

    extra_args(ap)：可选钩子，给该 step 挂自己的专属参数
    （例如 step6 的 --adopt-frame）。这样每个 step 脚本不必重写 argparse 外壳，
    公共参数（--run-dir / --dry-run / --new-run）也保证一致。
    """
    ap = argparse.ArgumentParser(
        prog=f"python -m orchestrator.steps.step{step_id}_{name}",
        description=f"节点 {step_id}：{name}")
    add_common_args(ap)
    if extra_args:
        extra_args(ap)
    args = ap.parse_args()

    run_dir = resolve_run_dir(args)
    log = make_log(run_dir, step_id)
    try:
        state = RunState.load(run_dir, must_exist=False)
        if args.dry_run:
            state.set("dry_run", True)
        state.begin(step_id, name, log)
        try:
            status, data, note = body(args, state, log)
        except Exception as e:
            import traceback
            log(f"\n[异常] {type(e).__name__}: {e}")
            log(traceback.format_exc())
            state.finish(step_id, "failed", {"error": f"{type(e).__name__}: {e}"},
                         log, note=f"{type(e).__name__}: {e}")
            log(f"\n[结果] 节点 {step_id} FAILED —— 只改这一份代码然后重跑本命令即可：")
            log(f"  python -m orchestrator.steps.step{step_id}_{name} "
                f"--run-dir \"{run_dir}\"")
            return 2
        state.finish(step_id, status, data, log, note=note)
        state.set("last_step", str(step_id))
        state.set("last_status", status)
        state.save()
        # "skipped" 是**按参数主动跳过**，不算失败 —— 链条应当继续。
        if status not in ("ok", "skipped"):
            log(f"\n[结果] 节点 {step_id} {status.upper()} —— 可单独修改并重跑本命令：")
            log(f"  python -m orchestrator.steps.step{step_id}_{name} "
                f"--run-dir \"{run_dir}\"")
            return 3
        log(f"\n[结果] 节点 {step_id} {status.upper()}")
        nxt = next_step_hint(step_id)
        if nxt.startswith("("):
            log("  这是链条的最后一节。")
        else:
            log(f"  下一步：python -m orchestrator.steps.{nxt} "
                f"--run-dir \"{run_dir}\"")
        return 0
    finally:
        log.close()


STEP_ORDER = ["1", "2", "4", "5", "6", "7", "8", "9"]

STEP_NAMES = {
    "1": "check_admin",
    "2": "launch",
    "4": "wait_second_layer",
    "5": "wait_ready",
    "6": "first_frame",
    "7": "foreground",
    "8": "run_task",
    "9": "cleanup",
}


def next_step_hint(step_id):
    try:
        i = STEP_ORDER.index(str(step_id))
    except ValueError:
        return "step1_check_admin"
    if i + 1 < len(STEP_ORDER):
        n = STEP_ORDER[i + 1]
        return f"step{n}_{STEP_NAMES[n]}"
    return "(链条结束)"


def step_module(step_id):
    n = str(step_id)
    return f"orchestrator.steps.step{n}_{STEP_NAMES[n]}"


def copy_into_run(state, src, tag):
    """把一张外部图片拷进 run-dir，返回新路径（供 --adopt-* 用）。"""
    dst = state.shot_path(tag)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return dst
