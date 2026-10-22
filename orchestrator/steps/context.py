"""steps.context — 断点式拆分：各 step 之间唯一的交接面

**目的**：把 `orchestrator/orchestrator.py` 里那条一气呵成的链条，按 README §5
的节点位置切成若干份**独立可单跑**的脚本。任意一环出错，都能只打开那一份代码
修改并单独重跑，不必碰其他代码块。

三条设计约束（这是"断点"能成立的前提）：

  1. **单一交接面**：step 之间**只**通过 `<run-dir>/state.json` 与若干 PNG 文件
     通信，不共享 Python 对象、不共享内存。任何一个 step 换个进程跑，结果一样。
  2. **每个 step 可单跑**：`python -m orchestrator.steps.common.step6_first_frame --run-dir <dir>`
   （模组路径由**程序自己的清单**决定，见 `steps/chain.py` 与 `main.py --list`）
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

# 链条是**属于程序**的（docs/adr/0005）：节点清单在 apps/<key>/nodes/__init__.py，
# 本模块只按清单算「这一步该跑哪个模组」。chain 是叶子模块（只 import importlib），
# 不会与本模块成环。
from . import chain  # noqa: E402  (放在 ROOT 之后，便于阅读)


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

    # ⚠️ **FAULT #37（实测 2026-10-18）**：Windows 上「写 tmp + `os.replace`」与
    #    「别处只读打开同一文件」是**互斥**的 —— CPython 的 `open()` 只共享
    #    READ|WRITE、**不共享 DELETE**，于是 `MoveFileExW` 返回
    #    `ERROR_ACCESS_DENIED`(5)。GUI 每 120ms 读一次 `state.json`
    #    （`gui/runner.py::StateWatcher`），撞车率实测 **7.8%**
    #    （`probe/_probe_state_race.py`：10233 次替换失败 794 次，错误码全是 5）。
    #    真实后果：节点 6 抓完首帧写 `add_shot` 时抛 PermissionError → 整节点 FAILED
    #    （run-20261018-131146）。
    #    ⇒ 替换**必须重试**。读侧单次持锁约 10ms，退避 12 次（合计 >0.6s）足够。
    SAVE_RETRIES = 12
    SAVE_BACKOFF_S = 0.01

    def save(self):
        os.makedirs(self.run_dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.raw, f, ensure_ascii=False, indent=2)
        delay = self.SAVE_BACKOFF_S
        for attempt in range(self.SAVE_RETRIES):
            try:
                os.replace(tmp, self.path)
                return
            except OSError as e:
                # 5 = ERROR_ACCESS_DENIED（目标被只读打开，最常见）
                # 32 = ERROR_SHARING_VIOLATION（对方要求独占）—— 同一类冲突，一起重试
                if getattr(e, "winerror", None) not in (5, 32):
                    raise
                if attempt == self.SAVE_RETRIES - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.2)

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

    ⚠️ 发现的是**本程序的目标窗口**（由 `program_key` 决定），
    不是写死的 ok-ww —— 否则 ok-nte 流程会去找 ok-ww 的窗口，
    找不到就回退到 state.json 里的旧 hwnd，**静默操作另一个程序**。
    """
    from .. import programs as programs_mod
    from .. import window
    prog = programs_mod.get(program_key(state))
    info = window.find_window(program=prog)
    if info:
        if log and state.get("hwnd") not in (None, info["hwnd"]):
            log(f"  hwnd 重新发现：{state.get('hwnd')} -> {info['hwnd']}（INV-14）")
        state.set("hwnd", info["hwnd"])
        state.set("pid", info["pid"])
        return info["hwnd"]
    old = state.get("hwnd")
    if log:
        log(f"  [警告] 标题正则未发现 {prog.display} 窗口，"
            f"回退到 state.json 记录的 hwnd={old}")
    return old


def require_hwnd(state, log=None):
    hwnd = rediscover_hwnd(state, log=log)
    if not hwnd:
        from .. import programs as programs_mod
        prog = programs_mod.get(program_key(state))
        raise StateError(
            f"没有可用的窗口句柄：标题正则没发现 {prog.display} 窗口，"
            f"state.json 里也没有记录。\n"
            f"  => 先跑 step4（等待第二层），或确认 --target 指定正确"
            f"（当前 {prog.key}）。")
    return hwnd


def program_key(state=None, args=None):
    """确定**本次运行的目标程序**（`"ww"` / `"nte"`）。

    优先级（从高到低）——

      1. `state.json` 里的 `program`（主控在开跑时写一次，**全链共享**）
      2. `--target` 命令行（**手工单跑**某个 step 时用）
      3. 默认 `programs.DEFAULT`（= ok-ww，保持既有调用方行为不变）

    ## 为什么程序名要放在 state.json 而不是每节命令行

    每一节都是**独立子进程**（`main.py` 用 subprocess 拉起），命令行只传
    `--run-dir`。若把程序名放命令行，就得给 8 个节点逐一加参数、并在
    `PASSTHROUGH` 里登记；放 state.json 则**一次写入、全链可见**，
    且「同一个运行目录必属同一个程序」这个事实**天然成立**（不会串味）。

    ## 为什么不是「自动探测」

    `programs.detect()` 能按进程反推，但它**会猜**：两个程序同时开着时，
    探测结果取决于枚举顺序。编排是**批量、无人值守**的，猜错会静默操作
    另一个程序（正是 FAULT #12 那一类失效）。故这里只认**显式指定**，
    探测只作为**交叉校验**（见 `resolve_program`）。
    """
    from .. import programs as programs_mod
    if state is not None:
        key = state.get("program")
        if key:
            try:
                return programs_mod.get(key).key
            except KeyError:
                # 配置写错 ⇒ 响亮报错，**不回落默认**（否则静默跑另一个程序）
                raise StateError(
                    f"state.json 里的 program={key!r} 不是已知程序；"
                    f"已知：{sorted(programs_mod.BY_KEY)}")
    tgt = getattr(args, "target", None) if args is not None else None
    if tgt:
        return programs_mod.get(tgt).key
    return programs_mod.DEFAULT.key


def resolve_program(state=None, args=None, log=None):
    """取本程序的 Program 记录，并**交叉校验**实际进程（不一致就告警）。

    交叉校验的意义：`--target nte` 却跑着 ok-ww，是**静默错配**的温床
    （点对了坐标、抓对了帧，但操作的是另一个程序）。这里只**告警不阻止**
    —— 因为「目标程序尚未启动」是合法状态（节点 2 就发生在启动之前）。
    """
    from .. import programs as programs_mod
    from .. import window as window_mod
    key = program_key(state, args)
    prog = programs_mod.get(key)
    if log:
        others = [p for p in programs_mod.ALL if p.key != prog.key
                  and window_mod.running(p)]
        if others:
            log(f"  [警告] 目标程序是 {prog.display}，但同时发现"
                f"{'、'.join(p.display for p in others)} 在运行 —— "
                f"请确认操作对象（本编排只操作 {prog.display}）")
    return prog


# ------------------------------------------------------------ 命令行共用


def _target_arg(text):
    """`--target` 的单程序校验（argparse type）。

    节点级只允许一个程序：`--target ww,nte` 在这里是**歧义**（这个节点该
    操作谁？），必须在解析参数时就报错，而不是等到 state.json 里读出
    一个键名再 `programs.get()` 抛 KeyError。清单来源见 orchestrator/targets.py。
    """
    from .. import targets
    try:
        return targets.validate_choices_flag(text)
    except targets.TargetError as e:
        raise argparse.ArgumentTypeError(str(e))


def add_common_args(ap):
    """给每个 step 脚本装上统一的参数。"""
    ap.add_argument("--run-dir", default=None,
                    help="运行目录（存放 state.json 与抓图）。省略时取最近一次运行。")
    ap.add_argument("--dry-run", action="store_true",
                    help="只做校验与定位，不点击、不杀进程")
    ap.add_argument("--new-run", action="store_true",
                    help="强制新建一个运行目录（否则沿用 --run-dir / 最近一次）")
    # --target 只对**手工单跑**某个 step 时有用：正常链路里程序名已写在
    # state.json（见 program_key）。默认 None 表示「跟随 state.json」。
    # 取值不写死在这里 —— 清单的唯一来源是 orchestrator/targets.py。
    ap.add_argument("--target", default=None, type=_target_arg, metavar="KEY",
                    help="目标程序（任一 programs.ALL 里的 key，如 ww / nte）。"
                         "省略时跟随 state.json；手工单跑某节时用它指定。"
                         "**一个节点只能有一个程序**（要跑多个请用主控）")
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


def run_step(step_id, name, body, extra_args=None, chain_key=None):
    """step 脚本的统一外壳。

    body(args, state, log) -> (status, data, note)
    status 取 "ok" / "failed" / "skipped" / "timeout"；非 "ok" 时退出码非 0。

    extra_args(ap)：可选钩子，给该 step 挂自己的专属参数
    （例如 step6 的 --adopt-frame）。这样每个 step 脚本不必重写 argparse 外壳，
    公共参数（--run-dir / --dry-run / --new-run）也保证一致。

    chain_key：**程序专属节点**必传，值为该程序的 key（apps/<key>/nodes/*.py）。
    共用节点（steps/common/*.py）不传 —— 它服务所有程序，程序从 state.json /
    --target 解析。传了就是一道自检：解析出的程序必须恰好是它，且该程序的
    链条里必须真有「节点 step_id + 档名 name」。对不上就**拒绝执行** ——
    跑下去会用错程序的定位链，且是静默的（不报错，只给错误结论）。
    """
    step_id = str(step_id)
    # usage 里显示哪个模组：parse 之前只有 chain_key 可依赖。
    stem = f"step{step_id}_{name}"
    mod_hint = (f"orchestrator.apps.{chain_key}.nodes.{stem}" if chain_key
                else f"orchestrator.steps.common.{stem}")
    ap = argparse.ArgumentParser(
        prog=f"python -m {mod_hint}",
        description=f"节点 {step_id}：{name}")
    add_common_args(ap)
    if extra_args:
        extra_args(ap)
    args = ap.parse_args()

    run_dir = resolve_run_dir(args)
    log = make_log(run_dir, step_id)
    try:
        state = RunState.load(run_dir, must_exist=False)
        prog = resolve_program(state, args, log=log)
        mod = _require_node(prog, step_id, name, chain_key, log)
        if mod is None:
            return 2
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
            log(f"  python -m {mod} --run-dir \"{run_dir}\"")
            return 2
        state.finish(step_id, status, data, log, note=note)
        state.set("last_step", str(step_id))
        state.set("last_status", status)
        state.save()
        # "skipped" 是**按参数主动跳过**，不算失败 —— 链条应当继续。
        if status not in ("ok", "skipped"):
            log(f"\n[结果] 节点 {step_id} {status.upper()} —— 可单独修改并重跑本命令：")
            log(f"  python -m {mod} --run-dir \"{run_dir}\"")
            return 3
        log(f"\n[结果] 节点 {step_id} {status.upper()}")
        nxt = chain.next_of(prog.key, step_id)
        if nxt is None:
            log("  这是链条的最后一节。")
        else:
            log(f"  下一步：python -m {chain.module(prog.key, nxt)} "
                f"--run-dir \"{run_dir}\"")
        return 0
    finally:
        log.close()


def _require_node(prog, step_id, name, chain_key, log):
    """校验「本入口文件 + 本节点」确实在该程序的链条里；返回该跑哪个模组。

    链条**属于程序**（docs/adr/0005）：同一个档名在不同程序下可能是共用骨架，
    也可能是程序专属实现；某个程序还可能压根没有这一节。所以每次执行都查一遍
    清单，而不是相信文件名 —— 用错程序的定位链是静默的错误（不报错，只给错误结论）。
    """
    if chain_key is not None and chain_key != prog.key:
        log(f"[!!] 本文件属于程序 {chain_key}，但运行目录/--target 指向 {prog.key}")
        log("     拒绝执行 —— 否则会用错程序的定位链（静默给出错误结论）")
        log(f"     要跑 {chain_key}：python -m orchestrator.steps.main "
            f"--target {chain_key} --only {step_id}")
        return None
    node = chain.by_id(prog.key, step_id)
    if node is None:
        log(f"[!!] 程序 {prog.key} 的节点链里没有节点 {step_id}"
            f"（它有：{', '.join(chain.ids(prog.key))}）")
        return None
    if node.name != f"step{step_id}_{name}":
        log(f"[!!] 程序 {prog.key} 的节点 {step_id} 是 {node.name}，"
            f"不是本文件的 step{step_id}_{name}")
        log(f"     清单见 orchestrator/apps/{prog.key}/nodes/__init__.py")
        return None
    return chain.module(prog.key, node)


def copy_into_run(state, src, tag):
    """把一张外部图片拷进 run-dir，返回新路径（供 --adopt-* 用）。"""
    dst = state.shot_path(tag)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return dst
