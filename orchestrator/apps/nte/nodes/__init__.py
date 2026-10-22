"""ok-nte 的节点链（本程序自己的，不是共用九节点）。

节点数量、编号、顺序、每节用哪份实现，**只在这一份字面量里**（docs/adr/0005）。
改这个程序的链条 = 改这个文件；别的程序看到的变化是零。

how to read：
    shared=True  实现在 steps/common/<name>.py（程序无关的骨架）
    shared=False 实现在 apps/nte/nodes/<name>.py（只服务本程序）
"""
# 与 ok-ww 的链条同形：差异全在节点 8（复选列表 + 右下角唯一「开始」按钮 +
# 游戏启动等待 + 日志逐项判完成）。

from ....steps.chain import Node


NODES = [
    Node("1", "step1_check_admin", "提权检查",
         "非管理员直接中止（INV-7）", shared=True),
    Node("2", "step2_launch", "启动目标程序",
         "拉起第一层，它自行启动第二层", shared=True),
    Node("4", "step4_wait_second_layer", "等待窗口出现",
         "窗口持有者出现（第二层 Qt 窗口）", shared=True),
    Node("5", "step5_wait_ready", "等待窗口就绪",
         "标题完整 + 尺寸达标 + 采样稳定", shared=True),
    Node("6", "step6_first_frame", "抓首帧并校验",
         "INV-1/13/17/22 + 侧栏任务图标身份校验", shared=True),
    Node("7", "step7_foreground", "置前台",
         "INV-8/22/23 的前置关", shared=True),
    Node("8", "step8_run_task", "任务循环",
         "导航->定位->点击->验证->等待完成", shared=False),
    Node("9", "step9_cleanup", "退出与清理",
         "正常完成不杀；超时/失败才杀", shared=True),

]
