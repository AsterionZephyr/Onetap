"""终态字符串常量 —— 无依赖的叶子模块（docs/adr/0003）。

为什么要单独一个文件：
  orchestrator/verdict.py 里定义过这五个常量，而迁移到 orchestrator/apps/zmd.py
  的判据代码要用它们。若 apps 直接 from ..verdict import RUNNING，就形成
  verdict -> apps.zmd -> verdict 的循环 import（verdict 侧是在文件尾部 import，
  实际能跑，但顺序一变就炸），更违反「专属模块不反向依赖共用层」的约定。

  状态字符串是**叶子**：它不 import 任何东西，谁都可以 import 它。故拆到这里，
  verdict.py 与 apps/*.py 都从它取，字符串只写一遍。

取值与 orchestrator/orchestrator.py 的 COMPLETED/TIMEOUT/... 是两套
（那一套是**节点退出**语义，这一套是**任务终态**语义），别混用。
"""

SUCCESS = "success"
FAILED = "failed"
UNKNOWN = "unknown"
NO_TASK = "no_task"
RUNNING = "running"
# --------------------------------------------------------------------------
# 节点结果（第二组）：orchestrator.orchestrator 里的 COMPLETED/TIMEOUT/STALLED。
#
# 与上面五个**不是**同一套语义：上面是「任务终态」（verdict 判出来的），
# 这里是「节点 8 的结论」（finish() 再把它映射成 ok/timeout/failed/skipped）。
# 放在同一个叶子模块里，只是为了让 apps/*.py 不必 import 共用层就能拿到同批字符串。
COMPLETED = "completed"
TIMEOUT = "timeout"
STALLED = "stalled"

# --------------------------------------------------------------------------
# 共用日志标记：ok-script 系的 **两个**程序（ok-ww / ok-nte）把游戏退出写进同一句，
# 字面量完全相同。原先它是 verdict.py 的模块级 NTE_TERMINAL_MARK，被 ww_verdict
# 直接裸用；迁到 apps/ 之后两个程序各自持名，字面量只在本叶子模块写一遍 ——
# 改一处不会漏改另一处（漏改的后果是静默：判据永远不认终止标记 ⇒ 恒 RUNNING）。
TERMINAL_MARK_EXIT_GAME = (
    r"TaskExecutor:Successfully Executed Task, Exiting Game and App!")
