"""orchestrator.steps — 断点式编排：每个节点一个可单跑的脚本

**为什么要拆**：最初是一条一气呵成的链条（`orchestrator/orchestrator.py` 里
顺序调用 node1..node9），任意一环出错都要改那个几百行的文件、并从头重跑整条链。
拆开后每个节点一个独立脚本，彼此只通过 `<run-dir>/state.json` 与 PNG 通信：
出错时只打开**那一份**代码改，改完只**重跑那一份**，其他环节原样不动。

## 链条属于**程序**（docs/adr/0005）

节点清单不再写死在这里，也不写死在 main.py：每个程序在自己的
`orchestrator/apps/<key>/nodes/__init__.py` 里用一份 `NODES` 字面量声明
「我跑哪几节、按什么顺序、每节用哪份实现」。节点编号与数量都随程序而定 ——
MaaEnd 有专属的 5/6，ok-ww / ok-nte 用共用骨架，将来加的程序可以完全不一样。

    orchestrator/steps/chain.py     读清单：chain()/ids()/by_id()/module()/next_of()
    orchestrator/steps/common/      程序无关的节点实现（不认识任何具体程序）
    orchestrator/steps/main.py      按清单逐节起子进程（不解释任何业务）

查看某个程序跑哪几节：

    python -m orchestrator.steps.main --list

单跑一节（模组路径由程序的清单决定，见 --list；共用节点在 steps/common 下，
程序专属节点在 apps/<key>/nodes 下）：

    python -m orchestrator.steps.common.step6_first_frame --run-dir <dir> --target zmd
    python -m orchestrator.apps.zmd.nodes.step6_first_frame --run-dir <dir>

一键跑完整条链：

    python -m orchestrator.steps.main --pre-clean
"""

from . import chain
from . import context

__all__ = ["chain", "context"]
