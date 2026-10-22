"""gui.chain — 按目标程序读取节点清单（ast 静态读），以及它与磁盘的一致性校验

## 节点链**属于程序**（docs/adr/0005）

每个 `orchestrator/apps/<key>/nodes/__init__.py` 用一份 `NODES` 字面量声明
该程序跑哪几节：

    Node("6", "step6_first_frame", "抓首帧并校验",
         "INV-1/13/17/22 + 身份校验", has_args=True, shared=True)

    sid       节点编号，程序内唯一（--only/--from/--to 用的就是它）
    name      档名，也决定实现落在哪个模组（见 module()）
    label     中文名（界面上的行标题）
    why       一行说明
    has_args  该节点有程序专属参数（GUI 标 ★）
    shared    True  = 实现在 orchestrator/steps/common/<name>.py
              False = 实现在 orchestrator/apps/<key>/nodes/<name>.py

## 为什么用 ast **静态读**，而不是 import 清单模组

GUI 是**跳板**：清单或节点代码写坏的时候，你还得能打开界面去修它。若这里
`import orchestrator.apps.<key>.nodes`，就会连带 import 编排代码（win32、
程序相关模块）—— 任何一个坏掉，GUI 都跟着起不来，正好在最需要它的时候。

所以这里用 `ast` 只读字面量，**不执行任何代码**；只有静态读失败时才
**惰性** import `orchestrator.steps.chain` 兜底，并把原因记进
`verify_against_disk()`（界面上看得见，不是静默回落）。

## API

    keys()                 目标程序 key 列表（复用 gui/targets.py 的 ast 读取）
    nodes(key)             [(sid, label, name, why, has_args), ...]
    ids(key)               该程序的节点编号顺序
    node_of(key, sid)      内部记录（含 shared）
    module(key, node)      节点模组的全名
    step_file(key, node)   节点模组在磁盘上的绝对路径
    all_ids()              所有程序编号的并集（旧签名兼容用）
    verify_against_disk()  清单 vs 磁盘（空 = 一致；只返回问题，不抛异常）
    ROOT / rel() / default_run_root() / latest_run_dir()   既有行为不变
"""

import ast
import os

from . import targets as gui_targets

# 仓库根：gui/chain.py -> 上溯两层
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORCH_DIR = os.path.join(ROOT, "orchestrator")
STEPS_DIR = os.path.join(ORCH_DIR, "steps")          # 共用节点在它的 common/ 下
COMMON_DIR = os.path.join(STEPS_DIR, "common")
APPS_DIR = os.path.join(ORCH_DIR, "apps")

# 缓存：key -> ((mtime_ns, size), rows, error)
# 同一份清单在一次界面会话里会被读很多次（每行状态刷新），按 mtime 缓存；
# 清单被改过（mtime 变）就自动重读，不会拿旧清单骗人。
_CACHE = {}


# ---------------------------------------------------------------------------
# 读清单
# ---------------------------------------------------------------------------

def keys():
    """目标程序 key 列表，顺序 = gui/targets.py 读到的 programs.ALL 顺序。"""
    pairs, _problems = gui_targets.load()
    return [k for k, _d in pairs]


def manifest_path(key):
    """某程序的节点清单文件路径。"""
    return os.path.join(APPS_DIR, key, "nodes", "__init__.py")


def _str_const(node):
    """字符串字面量 -> str；否则 None（绝不 eval）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _bool_const(node):
    """布尔字面量 -> bool；不是字面量返回 None（调用方据此报问题）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _parse_manifest(source, path):
    """解析 `NODES = [Node(...), ...]`；返回 (rows, error_or_None)。"""
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as e:
        return [], f"静态解析失败（{type(e).__name__}）"

    literal = None
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "NODES"):
            literal = stmt.value
    if literal is None:
        return [], "没找到 `NODES = [...]` 字面量"
    if not isinstance(literal, ast.List):
        return [], "`NODES` 不是列表字面量"

    rows = []
    for i, el in enumerate(literal.elts, 1):
        where = f"NODES 第 {i} 项"
        if not (isinstance(el, ast.Call) and isinstance(el.func, ast.Name)
                and el.func.id == "Node"):
            return [], f"{where}不是 `Node(...)` 字面量"
        pos = list(el.args)
        kw = {k.arg: k.value for k in el.keywords if k.arg}

        def lit(index, name, default=""):
            if name in kw:
                return _str_const(kw[name])
            if index < len(pos):
                return _str_const(pos[index])
            return default

        def flag(index, name, default=False):
            if name in kw:
                return _bool_const(kw[name])
            if index < len(pos):
                return _bool_const(pos[index])
            return default

        sid, name = lit(0, "sid"), lit(1, "name")
        label, why = lit(2, "label"), lit(3, "why")
        has_args, shared = flag(4, "has_args"), flag(5, "shared")
        if not sid or not name:
            return [], f"{where}的 sid/name 不是字符串字面量"
        if has_args is None or shared is None:
            return [], f"{where}的 has_args/shared 不是布尔字面量"
        rows.append({"sid": sid, "name": name, "label": label or name,
                     "why": why or "", "has_args": has_args, "shared": shared})
    return rows, None


def _lazy_nodes(key):
    """兜底：惰性 import 编排的清单读取器（只有静态读失败时才调用）。"""
    try:
        from orchestrator.steps import chain as orch_chain
        found = orch_chain.chain(key)
    except Exception as e:            # noqa: BLE001  兜底路径，任何异常都不能让 GUI 起不来
        return [], f"{type(e).__name__}: {e}"
    return ([{"sid": n.sid, "name": n.name, "label": n.label,
              "why": n.why, "has_args": bool(n.has_args),
              "shared": bool(n.shared)} for n in found], None)


def _load_nodes(key):
    """返回 (rows, error_or_None)；**不抛异常**（GUI 必须能开）。"""
    path = manifest_path(key)
    try:
        st = os.stat(path)
    except OSError:
        _CACHE.pop(key, None)
        return [], f"程序 {key} 没有节点清单：{rel(path)}"

    stamp = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]

    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        return [], f"读不出节点清单 {rel(path)}（{type(e).__name__}）"

    rows, err = _parse_manifest(source, path)
    if err:
        # 静态读失败才回落 import —— 回落本身也在提示"清单形状不标准"。
        lazy_rows, lazy_err = _lazy_nodes(key)
        if lazy_rows:
            rows = lazy_rows
            err += f"；已回落到 orchestrator.steps.chain（{len(rows)} 节）"
        else:
            err += f"；回落 orchestrator.steps.chain 也失败（{lazy_err}）"
    _CACHE[key] = (stamp, rows, err)
    return rows, err


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def nodes(key):
    """该程序的节点清单：[(sid, label, name, why, has_args), ...]。

    读不出来返回 []（**不抛异常**），问题见 verify_against_disk()。
    """
    rows, _err = _load_nodes(key)
    return [(r["sid"], r["label"], r["name"], r["why"], r["has_args"])
            for r in rows]


def ids(key):
    """该程序的节点编号顺序（= 执行顺序）。"""
    return [r[0] for r in nodes(key)]


def node_of(key, sid):
    """按编号取内部记录（含 shared）；该程序没有这一节时返回 None。"""
    rows, _err = _load_nodes(key)
    for r in rows:
        if r["sid"] == str(sid):
            return r
    return None


def all_ids():
    """所有程序节点编号的并集（保持首次出现顺序）。

    只用于**兼容旧调用签名**（`set_node(sid, status, note)`）：判断第一个参数
    到底是"程序 key"还是"节点号"时，需要知道所有程序认哪些编号。
    """
    out = []
    for key in keys():
        for sid in ids(key):
            if sid not in out:
                out.append(sid)
    return out


def _resolve(key, node):
    """把 nodes() 的一行 / sid / orch 的 Node 对象解析成内部记录。"""
    if node is None:
        return None
    if isinstance(node, dict):
        return node_of(key, node.get("sid"))
    if isinstance(node, str):
        return node_of(key, node)
    if isinstance(node, tuple):
        return node_of(key, node[0]) if node else None
    if hasattr(node, "sid"):
        return node_of(key, node.sid)
    return None


def module(key, node):
    """该节点在**这个程序**的链条里对应的模组全名；不属于该程序时 None。"""
    rec = _resolve(key, node)
    if rec is None:
        return None
    if rec["shared"]:
        return f"orchestrator.steps.common.{rec['name']}"
    return f"orchestrator.apps.{key}.nodes.{rec['name']}"


def module_of(key, sid):
    """按编号取模组全名；该程序没有这个节点时 None。"""
    return module(key, sid)


def step_file(key, node):
    """该节点模组在磁盘上的绝对路径。

    shared=True  -> orchestrator/steps/common/<name>.py
    shared=False -> orchestrator/apps/<key>/nodes/<name>.py
    """
    rec = _resolve(key, node)
    if rec is None:
        raise KeyError(f"程序 {key} 的链条里没有节点 {node!r}")
    base = COMMON_DIR if rec["shared"] else os.path.join(APPS_DIR, key, "nodes")
    return os.path.join(base, f"{rec['name']}.py")


# ---------------------------------------------------------------------------
# 一致性校验（供界面状态栏 / 启动日志用）
# ---------------------------------------------------------------------------

def verify_against_disk():
    """把**每个程序**的清单与磁盘比对，返回问题列表（空 = 一致）。

    检查这些情况（都是"清单与磁盘/程序列表漂移了"的信号）：

      1. 清单读不出 / 静态形状不标准 / 静态读失败后回落了 import；
      2. 清单里的节点**文件不存在**（共用或专属）；
      3. 节点目录里出现了清单**没有**的专属节点文件；
      4. common/ 里出现了**没有任何程序**声明的共用节点文件；
      5. apps/ 下有节点清单、却不在目标程序列表里的程序。

    仅返回问题，不抛异常：GUI 必须能在链条不完整时照常打开。
    """
    problems = []
    pairs, _target_problems = gui_targets.load()
    declared = set()
    shared_names = set()

    for key, display in pairs:
        declared.add(key)
        mpath = manifest_path(key)
        if not os.path.isfile(mpath):
            problems.append(f"{display}（{key}）没有节点清单：{rel(mpath)}")
            continue

        rows, err = _load_nodes(key)
        if err:
            problems.append(f"{display}（{key}）的节点清单：{err}")
        if not rows:
            problems.append(
                f"{display}（{key}）的节点清单是空的 —— 这条链跑不了")
            continue

        seen = set()
        for r in rows:
            if r["sid"] in seen:
                problems.append(
                    f"{display}（{key}）的节点编号重复：{r['sid']}")
            seen.add(r["sid"])

            p = step_file(key, r)
            if not os.path.isfile(p):
                kind = "共用" if r["shared"] else "专属"
                problems.append(
                    f"{display}（{key}）的节点 {r['sid']}（{r['label']}）"
                    f"缺{kind}实现：{rel(p)}")
            if r["shared"]:
                shared_names.add(r["name"])

        owned = {r["name"] + ".py" for r in rows if not r["shared"]}
        ndir = os.path.join(APPS_DIR, key, "nodes")
        if os.path.isdir(ndir):
            for fn in sorted(os.listdir(ndir)):
                if fn.endswith(".py") and fn.startswith("step") and fn not in owned:
                    problems.append(
                        f"{rel(ndir)} 里有清单未登记的专属节点文件：{fn}"
                        f"（若是有意新增，请写进该程序的 NODES）")
        else:
            problems.append(
                f"{display}（{key}）的节点目录不存在：{rel(ndir)}")

    if os.path.isdir(COMMON_DIR):
        known = {name + ".py" for name in shared_names}
        for fn in sorted(os.listdir(COMMON_DIR)):
            if fn.endswith(".py") and fn.startswith("step") and fn not in known:
                problems.append(
                    f"{rel(COMMON_DIR)} 里有清单未登记的共用节点文件：{fn}"
                    f"（没有任何程序的 NODES 声明它）")

    if os.path.isdir(APPS_DIR):
        for name in sorted(os.listdir(APPS_DIR)):
            if name in declared:
                continue
            p = os.path.join(APPS_DIR, name, "nodes", "__init__.py")
            if os.path.isfile(p):
                problems.append(
                    f"apps/{name} 有节点清单，但不在目标程序清单里"
                    f"（programs.ALL / gui/targets.py 漏了这个程序？）")
    return problems


# ---------------------------------------------------------------------------
# 路径与运行目录（既有行为不变）
# ---------------------------------------------------------------------------

def rel(path):
    """转成相对仓库根的路径，便于显示（失败时原样返回）。"""
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path


def default_run_root():
    """运行目录的根（与 steps/context.py 的 DEFAULT_RUN_ROOT 一致）。"""
    return os.path.join(ROOT, "logs", "runs")


def latest_run_dir():
    """最近一次运行目录；没有则 None。按 mtime 取最新。"""
    root = default_run_root()
    if not os.path.isdir(root):
        return None
    cands = [os.path.join(root, d) for d in os.listdir(root)
             if os.path.isdir(os.path.join(root, d))]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)
