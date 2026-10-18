"""gui.targets — 目标程序清单（GUI 侧，**独立声明**）

## 为什么这里还有一份，而不是直接 import orchestrator

与 `gui/chain.py` 同一个理由：**GUI 是跳板**。主控 / 节点代码坏掉的时候，
你还得能打开界面去改它。若 `gui/app.py` 顶层 `import orchestrator.programs`，
那么 programs.py 里一个语法错误（或任何 import 期副作用失败）就会让 GUI
连窗口都开不出来 —— 正好在最需要它的时候。

所以这里：

  1. 用 `ast` **静态读** `orchestrator/programs.py`，只取 `Program(key=...,
     display=...)` 两个字面量（不执行任何代码，不 import）；
  2. 读不出来 / 读到的和预期不符 -> 用下面的 `FALLBACK`，并在界面上告警；
  3. `verify()` 把"磁盘上的清单"和"FALLBACK"比对，不一致就报出来。

⚠️ 这份 FALLBACK 是**第二处**声明（第一处是 programs.ALL）。这与
`gui/chain.py` 的 STEPS 是同一笔交易：多一处声明，换 GUI 的可启动性，
代价是可能漂移 —— 所以必须有 `verify()` 且界面上要看得见。
"""

import ast
import os

#: 兜底清单（磁盘解析失败时用）。顺序 = 默认执行顺序。
FALLBACK = [
    ("ww", "ok-ww"),
    ("nte", "ok-nte"),
]

PROGRAMS_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "orchestrator", "programs.py")


def _const(node):
    """取字符串字面量；不是字面量就返回 None（绝不 eval）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def read_programs(path=None):
    """静态读 programs.py，返回 [(key, display), ...]（按 ALL 的顺序）。

    读不出来返回空列表 —— 调用方请用 `load()`，它会回落 FALLBACK。
    """
    path = path or PROGRAMS_PY
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return []

    by_var = {}          # 变量名 -> (key, display)
    all_order = []       # ALL = [WW, NTE, ...] 里的变量名顺序

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        value = node.value
        # WW = Program(key="ww", display="ok-ww", ...)
        if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "Program":
            kw = {k.arg: k.value for k in value.keywords if k.arg}
            key, disp = _const(kw.get("key")), _const(kw.get("display"))
            if key and disp:
                by_var[tgt.id] = (key, disp)
        # ALL = [WW, NTE]
        elif tgt.id == "ALL" and isinstance(value, ast.List):
            for el in value.elts:
                if isinstance(el, ast.Name) and el.id in by_var:
                    all_order.append(by_var[el.id])
                elif isinstance(el, ast.Name):
                    all_order.append(None)      # 还没解析到，占位

    if all_order and all(x is not None for x in all_order):
        return all_order
    return list(by_var.values())


def load(path=None):
    """返回 ([(key, display), ...], problems)。problems 非空 = 界面要告警。"""
    disk = read_programs(path)
    problems = []
    if not disk:
        problems.append(
            f"读不出 {os.path.relpath(path or PROGRAMS_PY, os.path.dirname(PROGRAMS_PY))}"
            f" 里的 Program 声明，目标清单已回落兜底值（{len(FALLBACK)} 个）")
        return list(FALLBACK), problems

    if [(k, d) for k, d in disk] != [(k, d) for k, d in FALLBACK]:
        problems.append(
            "目标清单漂移：磁盘上 "
            + ", ".join(f"{k}={d}" for k, d in disk)
            + "；界面兜底 "
            + ", ".join(f"{k}={d}" for k, d in FALLBACK)
            + "（界面以此处的磁盘值为准；兜底值该同步了）")
    return disk, problems


def keys(pairs=None):
    return [k for k, _ in (pairs if pairs is not None else load()[0])]


def displays(pairs=None):
    return {k: d for k, d in (pairs if pairs is not None else load()[0])}
