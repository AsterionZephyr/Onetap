"""orchestrator.apps —— 每个目标程序的专属实现（docs/adr/0003）。

分工：
  orchestrator/ 其余模块 = **共用内核**（抓帧、置前台、点击、窗口发现、
  九节点骨架、state.json 协议）。它**不认识任何一个具体程序**。
  orchestrator/apps/<key>/ = 一个程序的**全部专属逻辑**（<key>/__init__.py：
  定位、身份证据、终态判据；<key>/nodes/：该程序自己的节点清单与专属节点）。

为什么这么切：三个目标的差异是结构性的（层数、窗口类、界面同构与否、完成信号
在画面里还是日志里），不能靠配置抹平；而把它们的代码混在同一文件里，任何一次
修改都可能波及另外两个程序 —— 且波及是**静默**的（不报错，只给错误结论）。

命名约定：模块名 = programs.Program.key（ww / nte / zmd）。
取值一律走 get(key)（懒 import：GUI 侧不应为了列个清单就 import numpy）。

⚠️ 专属模块**不得** import apps/<key>/nodes/step8_run_task —— 节点 8 模组在文件
   顶部 `from .. import (...)` 取 apps/<key> 的名字，反着 import 会成环。
   对 match / verdict 的依赖只允许**共用内核**（模板匹配、☰ 检测、侧栏项检测、
   LogWindow 这类三程序共用件）；旧名字（已迁到 apps 的那些）一律经共用层的
   __getattr__ 垫片惰性取用，不要直接 import 已迁走的名字。
"""

import importlib

# 程序 key -> 专项模块名。没迁的程序仍留在共用文件里，
# get() 对它抛 KeyError —— **不回落**，避免「以为改了专项模块其实没生效」。
ADAPTERS = {
    "ww": "orchestrator.apps.ww",
    "nte": "orchestrator.apps.nte",
    "zmd": "orchestrator.apps.zmd",
}


def available():
    """已专项管理的程序 key 列表。"""
    return sorted(ADAPTERS)


def get(key):
    """按程序 key 取专项模块（懒 import）。未迁移的程序抛 KeyError。"""
    name = ADAPTERS.get(key)
    if name is None:
        raise KeyError(
            f"程序 {key!r} 还没有专项模块（已迁移：{', '.join(available())}）；"
            "它的逻辑仍留在共用文件里，不要假设 apps 里有它。")
    return importlib.import_module(name)
