"""orchestrator.steps — 断点式编排：按 README §5 的节点拆成可单跑的脚本

**为什么要拆**：原来的 `orchestrator/orchestrator.py` 是一条一气呵成的链条
（`run()` 里顺序调用 node1..node9）。任意一环出错，都要改那个 479 行的文件、
并从头重跑整条链，代价高且容易连带影响别的环节。

拆分后：**每个节点一个独立脚本**，彼此只通过 `<run-dir>/state.json`
与 PNG 文件通信。于是：

  - 出错时只打开**那一份**代码修改；
  - 改完只**重跑那一份**（`python -m orchestrator.steps.stepN_xxx --run-dir <dir>`）；
  - 其他环节的代码与状态**原样不动**，不受影响。

详见 `context.py` 的模块说明（交接面契约）。

链条顺序（README §5）：

    1  提权检查              step1_check_admin
    2  启动 ok-ww.exe        step2_launch
    4  等待第二层窗口        step4_wait_second_layer
    5  等待窗口就绪          step5_wait_ready
    6  抓首帧 + 校验 + 身份   step6_first_frame
    7  置前台 + 可用性校验    step7_foreground
    8  任务循环（导航->定位->点击->验证->等待）  step8_run_task
    9  退出与清理            step9_cleanup

**没有节点 3**：实机复核证明「跨过第一层」这道关卡不存在（见 window.py 模块说明）。

一键跑完整条链：

    python -m orchestrator.steps.main --pre-clean
"""

from . import context

__all__ = ["context"]
