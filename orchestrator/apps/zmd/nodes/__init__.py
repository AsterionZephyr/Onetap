"""MaaEnd 的节点链（本程序自己的，不是共用九节点）。

节点数量、编号、顺序、每节用哪份实现，**只在这一份字面量里**（docs/adr/0005）。
改这个程序的链条 = 改这个文件；别的程序看到的变化是零。

how to read：
    shared=True  实现在 steps/common/<name>.py（程序无关的骨架）
    shared=False 实现在 apps/zmd/nodes/<name>.py（只服务本程序）
"""
# ★ MaaEnd 与另外两个程序**不同形**的地方都在 5/6/8 三节：
#   5  自我更新会在运行期间重启进程（换 hwnd）-> pre_ready 闸门
#   6  「更新完成」模态框会压暗身份锚点     -> pre_frame 闸门 + 绿色按钮身份
#   8  没有任务页/侧栏，只能读日志判完成   -> 整段 zmd_run（不套 push 骨架）

from ....steps.chain import Node


NODES = [
    Node("1", "step1_check_admin", "提权检查",
         "非管理员直接中止（INV-7）", shared=True),
    Node("2", "step2_launch", "启动目标程序",
         "拉起 MaaEnd.exe（单层，自己持窗口）", shared=True),
    Node("4", "step4_wait_second_layer", "等待窗口出现",
         "Tauri 顶层窗口出现（单层程序，没有第二层）", shared=True),
    Node("5", "step5_wait_ready", "等待窗口就绪 + 等自我更新",
         "先等自我更新收敛（会重启进程），再判就绪",
         has_args=True, shared=False),
    Node("6", "step6_first_frame", "抓首帧并校验",
         "点掉「更新完成」弹窗 + 底部绿色开始按钮身份校验",
         has_args=True, shared=False),
    Node("7", "step7_foreground", "置前台",
         "INV-8/22/23 的前置关", shared=True),
    Node("8", "step8_run_task", "任务循环",
         "单页任务 ID -> 开始 -> 只读日志判完成", shared=False),
    Node("9", "step9_cleanup", "退出与清理",
         "MaaEnd 跑完不退出：完成也留进程，失败才杀", shared=True),

]
