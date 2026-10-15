"""orchestrator.errors — 校验失败的中止信号

本框架的核心设计：**校验失败必须停手，不得用可疑数据继续算坐标**（FRAMEWORK §1）。
所有校验都用同一个异常类型上报，携带「哪一条不变量被破坏」，便于日志与退出码分类。
"""


class GuardFailure(Exception):
    """一条不变量被破坏，框架必须停手。

    属性：
      invariant: 不变量编号，如 "INV-1"
      detail:    人话说明，进日志
    """

    def __init__(self, invariant, detail):
        self.invariant = invariant
        self.detail = detail
        super().__init__(f"[{invariant}] {detail}")

    def __str__(self):
        return f"[{self.invariant}] {self.detail}"


class DiscoveryFailure(Exception):
    """环境前提不成立（未提权、找不到窗口、进程缺失）。"""
