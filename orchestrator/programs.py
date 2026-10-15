"""orchestrator.programs — 目标程序表（ok-ww / ok-nte）

**为什么要有这个模块**：框架原本把 ok-ww 的具体值**硬编码**在 `window.py`
（`OKWW_TITLE_RE` / `OKWW_EXE` / `OKWW_DIR` / 进程名列表 / 窗口类前缀）与
`cleanup.py` 里。接入 ok-nte 时若继续复制粘贴，就会得到两份**各自漂移**的常量，
而漂移是**静默**的：路径写错只会表现为「找不到进程」，不会报错。

本模块把「程序」抽成一条**声明式记录**，`window.py` / `cleanup.py` / 判据层
一律从这里取值。新增程序 = 加一条记录，不改逻辑。

## 两条实测事实决定了本表的设计

1. **两程序的窗口签名同构**：ok-ww 是「Qt 系窗口类 + 标题含 OK-WW」，
   ok-nte 是「Qt 系窗口类 + 标题含 ok-nte」（`probe/nte_main.py:35` 的注释与
   第 97 行的实测输出都印证）。故窗口发现用**同一套逻辑**，只是参数不同 ——
   不需要为每个程序写一个 `find_*_window`。

2. **两程序都是两层结构**：第一层 `*.exe` 负责自更新并拉起第二层，
   第二层是 `data/apps/<name>/working/` 下的 `pythonw.exe` 跑 `main.py`，
   **真正持有窗口的是第二层**（ok-ww 实测第一层 10 秒后自行退出，
   `Get-Process ok-ww` 返回空是正常的）。故「是否在运行」必须按
   **工作目录前缀**判定，而不是按 exe 名。

## ⚠️ 工作目录前缀是本表**唯一**的进程归属判据

`process_prefix` 必须指向 `data/apps/<name>/` 这一层，**不能**只写
`E:\\TOOLS\\ScriptsGames\\ok-ww`（太宽，会把同目录下的其它东西算进来），
也**不能**写死 `pythonw.exe`（机器上同时有别的 pythonw，如图中
`searxng-master\\.venv\\Scripts\\pythonw.exe`、`D:\\WORKs\\Anaconda\\pythonw.exe`）。

## 已核实的路径（2026-10-16 实机）

    ok-ww : E:\\TOOLS\\ScriptsGames\\ok-ww\\ok-ww.exe
            E:\\TOOLS\\ScriptsGames\\ok-ww\\data\\apps\\ok-ww\\python\\pythonw.exe
    ok-nte: E:\\TOOLS\\ScriptsGames\\ok-nte\\ok-nte.exe
            E:\\TOOLS\\ScriptsGames\\ok-nte\\data\\apps\\ok-nte\\working\\main.py
"""

import os
import re

# 窗口类前缀：两程序都实测为 Qt 自绘窗口（ok-ww `Qt6111QWindowIcon`，
# ok-nte 亦为 Qt）。前缀匹配以兼容 Qt 版本号变化。
QT_CLASS_PREFIX = "Qt"

# 第一层的 Tauri 外壳窗口类。ok-ww 的启动器窗口属此类，**不是**干活的那个；
# 实测本机 `Clash Verge` 也是 `Tauri Window`，故这个排除是**载荷性**的。
TAURI_CLASS = "Tauri Window"


class Program:
    """一个目标程序的声明式记录。

    字段全部是**数据**，没有任何行为分支 —— 行为留在 `window.py` / `cleanup.py`。

    key             : 稳定标识（`ww` / `nte`），配置与运行记录里用它
    display         : 人类可读名（日志用）
    exe             : 第一层可执行文件的**绝对路径**
    root_dir        : 安装根目录（`okww_running` 等归属判定用）
    process_prefix  : **进程归属判据** —— 进程 exe 路径需以此前缀开头。
                      指向 `data/apps/<name>` 这一层，见模块 docstring 的警告。
    process_names   : 用于 `list_processes` 的候选进程名（只是**缩小扫描面**，
                      真正的归属判定是 process_prefix）
    title_re        : 完整标题正则（就绪后形态）
    loose_title_re  : 宽松标题正则（第二层刚起、标题尚未成完整形态）
    ready_title_re  : 就绪判据用的标题正则（通常同 title_re）
    min_width/min_height : 窗口「可用」的尺寸下限
    """

    def __init__(self, key, display, exe, root_dir, process_prefix,
                 process_names, loose_title_re, ready_title_re,
                 min_width, min_height, game_names=None, game_title_re=None):
        self.key = key
        self.display = display
        self.exe = exe
        self.root_dir = root_dir
        self.process_prefix = os.path.normcase(os.path.abspath(process_prefix))
        self.process_names = list(process_names)
        self.loose_title_re = loose_title_re
        self.ready_title_re = ready_title_re
        self.min_width = min_width
        self.min_height = min_height
        # 目标游戏的进程名（用于超时兜底关闭）。**不能**用 exe 路径判定归属
        # —— 游戏装在 D:\GAMES\ 之类的目录下，与目标程序毫无路径关系。
        self.game_names = list(game_names or [])
        # 游戏主窗口标题正则（关窗前定位窗口用；实测两者都可为空标题）
        self.game_title_re = game_title_re or ""

    def owns_process(self, exe_path):
        """该进程是否属于本程序（按工作目录前缀判定）。

        ⚠️ 返回 False 而非抛异常：调用方在做**发现**，不是在断言。
        """
        if not exe_path:
            return False
        return os.path.normcase(os.path.abspath(exe_path)).startswith(
            self.process_prefix)

    def title_matches(self, title, ready=False):
        """标题是否像本程序。ready=True 时要求完整形态（含版本号）。

        ⚠️ INV-5：**绝不**用精确相等 —— 标题随版本号变化。
        """
        pat = self.ready_title_re if ready else self.loose_title_re
        return bool(title and re.search(pat, title))

    def __repr__(self):
        return f"<Program {self.key} {self.display!r}>"


# --- ok-ww ----------------------------------------------------------------
# 真实标题：`OK-WW v3.7.4 China  - OK-WW`（注意**两个空格**，实测）。
# 第一层标题是小写 `ok-ww`，故正则必须不区分大小写（INV-5）。
#
# ⚠️ FAULT #12：宽松正则**不能**裸用 `OK-WW` 之外的宽泛词 ——
# 本编排自己的 GUI 标题是「ok-ww 断点式编排 — GUI」，同样被裸正则命中。
# 故发现流程除标题外还必须排除「自家 PID」+「窗口类必须 Qt 系」，
# 这两条在 window.find_window 里实施（不在本表）。
WW = Program(
    key="ww",
    display="ok-ww",
    exe=r"E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe",
    root_dir=r"E:\TOOLS\ScriptsGames\ok-ww",
    process_prefix=r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww",
    process_names=["pythonw.exe", "ok-ww.exe"],
    loose_title_re=r"(?i)OK-WW",
    ready_title_re=r"(?i)OK-WW\s+v[\d.]+\s+\w+\s+-\s+OK-WW",
    min_width=1000,
    min_height=700,
    # 目标游戏：鸣潮。实测进程名 Client-Win64-Shipping.exe，
    # 窗口类 UnrealWindow、标题 '鸣潮  '（含两个尾随空格，实测）。
    game_names=["Client-Win64-Shipping.exe"],
    game_title_re=r"(?i)鸣潮|Wuthering\s*Waves",
)

# --- ok-nte ---------------------------------------------------------------
# 窗口签名实测自 `probe/nte_main.py`：class 含 Qt、标题含 `ok-nte`。
# 该脚本第 97 行打印「[发现] 标题含 ok-nte 的窗口」，是当时的验证方式。
#
# ⚠️ 与 ok-ww 的差异（FRAMEWORK §0.1 记有其它差异，此处只列与本表相关的）：
#   - 第一层的进程名是 `ok-nte.exe`；第二层**不是 pythonw.exe**，
#     而是 working 目录下由 pyappify 拉起的 python（实测日志里
#     `ok:ok-script init v1.4.13` 由 MainThread 输出）。
#     故 process_names 放宽到 python/pythonw 两者。
#
# ⚠️ FAULT #20（本表原先的判断是错的，已修）：
#     原注释写「ok-nte 标题**没有** ok-ww 那种固定形态，故 ready_title_re
#     只锚『含 ok-nte』，尺寸下限才是主要就绪判据」—— **这是错的**。
#     2026-10-16 实跑（run-20261016-011008）实测到第二层的完整生命周期：
#         未就绪：[ok-nte]                          （500x500 空壳）
#         已就绪：ok-nte v1.4.14 China  - ok-nte    （1500x1000）
#     即 ok-nte 的标题形态**与 ok-ww 完全同构**，只是名字不同。
#     原先 `ready_title_re = r"(?i)ok-nte"` 是**子串**判据，会连空壳一起放行
#     ⇒ 就绪判定实际上**只剩尺寸一道闸**，标题那一道形同虚设。
#     对照 ok-ww：'OK-WW' -> ready=False（正确拒绝空壳）；
#     ok-nte 旧判据：'ok-nte' -> ready=True（**错误放行空壳**）。
#     现改为与 ok-ww 同构的完整形态判据，两道闸都生效。
NTE = Program(
    key="nte",
    display="ok-nte",
    exe=r"E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe",
    root_dir=r"E:\TOOLS\ScriptsGames\ok-nte",
    process_prefix=r"E:\TOOLS\ScriptsGames\ok-nte\data\apps\ok-nte",
    process_names=["pythonw.exe", "python.exe", "ok-nte.exe"],
    loose_title_re=r"(?i)ok-nte",
    ready_title_re=r"(?i)ok-nte\s+v[\d.]+\s+\w+\s+-\s+ok-nte",
    min_width=800,
    min_height=600,
    # 目标游戏：Neverness To Everness。日志口径写 HTGame.exe（nte_verdict
    # 用它），清理时镜像名可能显示为 NTEGame —— 两种都列上。
    game_names=["HTGame.exe", "NTEGame.exe"],
    game_title_re=r"(?i)Neverness|^HTGame",
)


ALL = [WW, NTE]
BY_KEY = {p.key: p for p in ALL}

# 默认程序：**保持 ok-ww**，使既有调用方行为不变（本次改动不加回归）。
DEFAULT = WW


# --- 自检 -------------------------------------------------------------------
# 就绪标题判据必须能**区分空壳与就绪形态**。FAULT #20 就是这条没被守住：
# ok-nte 原用子串 `ok-nte` 当就绪判据，空壳也放行，标题闸形同虚设。
# 这个自检把它变成**开机即报**的错误，而不是等到实跑才发现。
_TITLE_CASES = [
    # (program, title, 期望 loose, 期望 ready)
    (WW,  "OK-WW",                            True,  False),
    (WW,  "OK-WW v3.7.4 China  - OK-WW",      True,  True),
    (WW,  "ok-ww 断点式编排 — GUI",              True,  False),  # FAULT #12 的自家标题
    (NTE, "ok-nte",                           True,  False),
    (NTE, "ok-nte v1.4.14 China  - ok-nte",   True,  True),
]


def self_check():
    """校验标题判据；返回问题描述列表（空列表 = 通过）。"""
    problems = []
    for prog, title, want_loose, want_ready in _TITLE_CASES:
        got_loose = prog.title_matches(title, ready=False)
        got_ready = prog.title_matches(title, ready=True)
        if got_loose != want_loose or got_ready != want_ready:
            problems.append(
                f"{prog.display} 标题 {title!r}: "
                f"loose={got_loose}（期望 {want_loose}）"
                f" ready={got_ready}（期望 {want_ready}）")
    # ready 必须是 loose 的子集：就绪形态当然也满足宽松判据
    for prog, title, _l, want_ready in _TITLE_CASES:
        if want_ready and not prog.title_matches(title, ready=False):
            problems.append(f"{prog.display} 标题 {title!r}: "
                            f"ready=True 但 loose=False（判据不自洽）")
    return problems


def get(key_or_program):
    """按 key 取程序记录；也接受已传入的 Program（幂等）。

    ⚠️ 未知 key **抛异常**而非回落默认 —— 回落会把「配置写错」
    变成「静默跑了另一个程序」。
    """
    if isinstance(key_or_program, Program):
        return key_or_program
    if key_or_program is None:
        return DEFAULT
    try:
        return BY_KEY[key_or_program]
    except KeyError:
        raise KeyError(
            f"未知的目标程序 {key_or_program!r}；已知：{sorted(BY_KEY)}")


def detect(program=None):
    """从**进程**反推当前跑的是哪个程序（发现窗口前用）。

    返回 Program 或 None。判据是 process_prefix（见模块 docstring）。
    """
    if program is not None:
        return get(program)
    from . import win32
    names = sorted({n for p in ALL for n in p.process_names})
    for name, pid, exe in win32.list_processes(names):
        for p in ALL:
            if p.owns_process(exe):
                return p
    return None
