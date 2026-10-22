"""每条目标程序**自己的**节点链（docs/adr/0005）。

节点**属于程序**，不属于引擎。每个 `orchestrator/apps/<key>/nodes/__init__.py`
用一份 `NODES` 字面量声明它自己的链条 —— 节点数量、编号、顺序、每个节点用
哪份实现，全在这一处。本模块只负责读出清单、算出「这个节点该跑哪个模组」。

## 为什么清单属于程序，而不是 main.py 里的一份 CHAIN

九节点同构只是**目前三个程序的巧合**，不是规律：

  - MaaEnd 的节点 5 要先等自我更新收敛、节点 6 要先点掉「更新完成」弹窗，
    这两件事 ok-ww / ok-nte 都没有；
  - ok-nte 的任务页结构与 ok-ww 不同构，节点 8 的定位链完全不同；
  - 以后加第 N 个程序，它的节点数**可以完全不一样**。

清单写死在 main.py 时，「这个程序有几个节点」在代码里没有单一出处，加一个
程序还得改共用文件。现在它在 `apps/<key>/nodes/__init__.py` 里，一眼看完。

## 清单字面量的形状

    Node("6", "step6_first_frame", "抓首帧并校验",
         "INV-1/13/17/22 + 身份校验", has_args=True, shared=True)

    sid       节点编号，程序内唯一 —— `--only/--from/--to` 用的就是它（不是序号）
    name      档名，也决定实现落在哪个模组（见 `module()`）
    label     中文名（GUI / 日志 / --list 都读它）
    why       一行说明（`--list` 打出来）
    has_args  该节点有专属参数（GUI 上标 ★）
    shared    True = 实现在 `steps/common/<name>.py`（程序无关的机制）；
              False = 实现在 `apps/<key>/nodes/<name>.py`（只服务本程序）

## ⚠️ 共用节点也必须写进**每个程序自己的**清单

不在别处被偷偷追加。一个程序的链条就是它清单里那几行，不多不少 —— 这样
「这个程序跑哪几步」只有一处可读，`programs.ALL` 与 GUI 都能静态 diff 出来。

## 归属规则（与 docs/adr/0003 一致）

`shared=True` 的节点**不认识任何具体程序**（不出现 "ww"/"nte"/"zmd"），
程序差异通过钩子参数传进去（见 steps/common/push.py 与 step5/step6 的 `run()`）。
程序专属节点**不 import 别的程序的节点模组**，也不 import 共用节点的模组去做分派。
"""

import importlib


class Node:
    """链条里的一节：编号 + 档名 + 给人看的文案 + 实现归属。"""

    __slots__ = ("sid", "name", "label", "why", "has_args", "shared")

    def __init__(self, sid, name, label, why="", has_args=False, shared=False):
        self.sid = str(sid)
        self.name = name
        self.label = label
        self.why = why
        self.has_args = bool(has_args)
        self.shared = bool(shared)

    def __repr__(self):
        kind = "共用" if self.shared else "专属"
        return (f"Node({self.sid}, {self.name}, {self.label!r}, "
                f"has_args={self.has_args}, {kind})")

    def row(self):
        """旧 `CHAIN` 的五元组形状（sid, label, name, why, has_args）。"""
        return (self.sid, self.label, self.name, self.why, self.has_args)


def chain(key):
    """程序 key 的节点清单（唯一来源：`apps/<key>/nodes/__init__.py::NODES`）。"""
    mod = importlib.import_module(f"orchestrator.apps.{key}.nodes")
    nodes = list(mod.NODES)
    _verify(key, nodes)
    return nodes


def _verify(key, nodes):
    """清单自洽性：空清单 / 编号重复 / 缺档名，都是**配置写错**，必须响亮报错。"""
    if not nodes:
        raise ValueError(f"程序 {key} 的节点清单是空的")
    seen = set()
    for n in nodes:
        if n.sid in seen:
            raise ValueError(f"程序 {key} 的节点编号重复：{n.sid}")
        seen.add(n.sid)
        if not n.name:
            raise ValueError(f"程序 {key} 的节点 {n.sid} 没有档名")


def ids(key):
    """该程序的节点编号顺序（= 执行顺序）。"""
    return [n.sid for n in chain(key)]


def by_id(key, sid):
    """按编号取节点；该程序没有这个节点时返回 None。"""
    for n in chain(key):
        if n.sid == str(sid):
            return n
    return None


def next_of(key, sid):
    """链条里 sid 之后的那一节（None = 已是链尾）。"""
    nodes = chain(key)
    for i, n in enumerate(nodes):
        if n.sid == str(sid):
            return nodes[i + 1] if i + 1 < len(nodes) else None
    return None


def module(key, node):
    """该节点在**这个程序**的链条里对应的模组名。"""
    if node.shared:
        return f"orchestrator.steps.common.{node.name}"
    return f"orchestrator.apps.{key}.nodes.{node.name}"


def module_of(key, sid):
    """按编号取模组名；该程序没有这个节点时返回 None。"""
    n = by_id(key, sid)
    return None if n is None else module(key, n)


def describe(key, sid):
    """给日志/报错用的一行：`节点 6 step6_first_frame（抓首帧并校验）`。"""
    n = by_id(key, sid)
    if n is None:
        return f"节点 {sid}（程序 {key} 的链条里没有这一节）"
    return f"节点 {n.sid} {n.name}（{n.label}）"


def check_all():
    """自检所有已注册程序的清单；返回可打印的报告行。

    `programs.ALL` 是程序的唯一来源（`targets.self_check()` 已守着顺序），
    这里再兜一层：每个程序都得有清单，且清单里的编号必须能用。
    """
    from .. import programs as programs_mod

    lines = []
    for prog in programs_mod.ALL:
        nodes = chain(prog.key)
        lines.append(
            f"  [OK] {prog.key:4s} {prog.display:8s} {len(nodes)} 个节点："
            + " ".join(n.sid for n in nodes))
    return lines
