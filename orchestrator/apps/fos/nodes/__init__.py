"""FOS（MPA）的节点链 —— 只有四节，且中间没有任何界面操作。

节点数量、编号、顺序、每节用哪份实现，**只在这一份字面量里**（docs/adr/0005）。

how to read：
    shared=True  实现在 orchestrator/steps/common/<name>.py（程序无关的骨架）
    shared=False 实现在 orchestrator/apps/fos/nodes/<name>.py（只服务本程序）

★ FOS 与另外三个程序不同形的地方**只有一处，但它很彻底**：FOS 没有可编排的
  界面（用户裁定：只启动 + 等待它自己退出并清理，不识别、不操作）。故 4/5/6/7
  四节（等窗口、等就绪、抓首帧、置前台）在这条链上**不存在** —— 不是"暂时禁用"，
  而是根本不需要。第 3 节换成专属的 step3_wait_exit（只读进程表）。
"""

from ....steps.chain import Node


NODES = [
    Node("1", "step1_check_admin", "提权检查",
         "非管理员直接中止（INV-7）", shared=True),
    Node("2", "step2_launch", "启动 FOS",
         "拉起 FOS.exe，之后什么都不做（无第二层）", shared=True),
    Node("3", "step3_wait_exit", "等它自己退出",
         "只读进程表：连续 3 次看不见 MPA 下的进程才算跑完",
         has_args=True, shared=False),
    Node("9", "step9_cleanup", "退出与清理",
         "正常完成不杀（它自己清理）；超时才收尸", shared=True),
]
