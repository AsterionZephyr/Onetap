"""orchestrator — ok-ww 黑盒编排框架

在**进程外**、以**真实光标**、**黑盒**地操作 ok-ww：

    启动 -> 等待第二层 -> 窗口就绪 -> 抓帧校验 -> 置前台
      -> 导航到任务页 -> 定位「每日任务/开始」 -> 点击 -> 等待完成
      -> 确认退出 / 超时清理

设计约束以 [HANDOFF.md](../docs/HANDOFF.md) 与 [FRAMEWORK.md](../docs/FRAMEWORK.md) 为准，
术语以 [CONTEXT.md](../docs/CONTEXT.md) 为准，架构决策见 [docs/adr/](../docs/adr/)。

本版本相对文档的三处**实测修正**（详见各模块说明）：

  1. **节点 3「跨过第一层」删除** —— 实机复核证明不存在这道关卡，第二层自行运行。
  2. **锚点改为可见锚点组合** —— 「每日任务」四字实测 2 个候选且最高分是错行（ADR 0002）。
  3. **完成判定需要「退出通知」资产** —— 横幅文案在完成态与卡死态完全相同。

用法：

    python -m orchestrator --dry-run      # 只校验与定位，不点击（推荐先跑这个）
    python -m orchestrator                # 完整执行
    python -m orchestrator --no-launch    # 假定 ok-ww 已在运行
"""

__version__ = "0.1.0"
