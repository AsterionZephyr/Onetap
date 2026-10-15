"""gui — ok-ww 断点式编排的两页 GUI（tkinter，零新增依赖）

    gui/
      __init__.py    本文件
      editor.py      CodeEditor 组件（行号 + 增量高亮 + 保存往返）
      chain.py       步骤清单的**单一来源** + 与 steps/ 目录的一致性校验
      runner.py      子进程驱动 steps/main.py + state.json 轮询 + 整树终止
      app.py         两页界面（Notebook）
      __main__.py    入口：python -m gui

设计依据：
  - [docs/GUI-DEPENDENCY-DECISION.md](../docs/GUI-DEPENDENCY-DECISION.md)（选型）
  - [STEPS-README.md](../STEPS-README.md)（节点链与 state.json 契约）
  - [GUI-README.md](../GUI-README.md)（使用手册）

**本 GUI 不 import 任何 orchestrator 业务模块。** 它只做三件事：
读文件、写文件、起子进程。这样即使某个节点文件语法坏了，GUI 照样能开起来
去修它 —— 这是"跳板"的硬要求。
"""

__version__ = "0.1.0"
