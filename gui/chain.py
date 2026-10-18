"""gui.chain — 步骤清单的单一来源，以及它与 steps/ 目录的一致性校验

**为什么要在这里硬编码一份清单，而不 import `orchestrator.steps.main`**：

    GUI 是"跳板"。当某个节点文件被改坏（语法错误、import 失败）时，
    你必须还能打开 GUI 去修它。若 GUI import 了编排代码，`main.py` 一旦
    坏掉，GUI 就跟着起不来 —— 正好在你最需要它的时候失效。

所以：清单在这里**独立声明**，启动时与磁盘上的实际文件**比对**，
不一致就**在界面上警告**（而不是崩溃）。

⚠️ 修改链条时**两处都要改**：这里，以及 `orchestrator/steps/main.py` 的 `CHAIN`。
    `verify_against_disk()` 会替你发现漏改 —— 这是刻意的摩擦，不是疏忽。
"""

import os

# 仓库根：gui/chain.py -> 上溯两层
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEPS_DIR = os.path.join(ROOT, "orchestrator", "steps")

# ---------------------------------------------------------------------------
# 步骤清单
#
#   (节点号, 中文名, 模块名, 一句说明, 是否有专属参数)
#
# 节点号**沿用 orchestrator 的编号**：没有节点 3 —— 实机复核证明
# 「跨过第一层」这道关卡不存在（见 orchestrator/window.py 模块说明）。
# 编号保留原样是为了让界面上的 `[6]` 与历史日志、与 STEPS-README 对得上。
# ---------------------------------------------------------------------------

STEPS = [
    ("1", "提权检查",         "step1_check_admin",       "非管理员直接中止（INV-7）",        True),
    ("2", "启动目标程序",     "step2_launch",            "拉起第一层，它自行启动第二层",      True),
    ("4", "等待窗口出现",     "step4_wait_second_layer", "窗口持有者（ww/nte=第二层 Qt；zmd=单层）", False),
    ("5", "等待窗口就绪",     "step5_wait_ready",        "标题完整 + 尺寸达标 + 采样稳定",    False),
    ("6", "抓首帧并校验",     "step6_first_frame",       "INV-1/13/17/22 + 身份校验",        True),
    ("7", "置前台",           "step7_foreground",        "INV-8/22/23 的前置关",             False),
    ("8", "任务循环",         "step8_run_task",          "导航→定位→点击→验证→等待完成",      True),
    ("9", "退出与清理",       "step9_cleanup",           "正常完成不杀；超时/失败才杀",       True),
]

STEP_IDS = [s[0] for s in STEPS]
BY_ID = {s[0]: s for s in STEPS}


def step_file(mod_name):
    """步骤模块名 -> 磁盘上的绝对路径。"""
    return os.path.join(STEPS_DIR, f"{mod_name}.py")


def all_files():
    """清单里每一步对应的文件路径，按链条顺序。"""
    return [(sid, step_file(mod)) for sid, _n, mod, _w, _a in STEPS]


def rel(path):
    """转成相对仓库根的路径，便于显示（失败时原样返回）。"""
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path


def verify_against_disk():
    """把清单与 steps/ 目录比对，返回问题列表（空 = 一致）。

    检查三类问题：
      1. 清单里的文件**不存在** —— 链条会断；
      2. 目录里出现了清单**没有**的 stepN_*.py —— 你可能漏改了这里；
      3. main.py 的 CHAIN 与这里不一致 —— 两处声明漂移了。

    仅返回问题，不抛异常：GUI 必须能在链条不完整时照常打开。
    """
    problems = []

    for sid, _n, mod, _w, _a in STEPS:
        p = step_file(mod)
        if not os.path.isfile(p):
            problems.append(f"节点 {sid} 的文件不存在：{rel(p)}")

    # 目录里多出来的 stepN_*.py
    known = {mod + ".py" for _s, _n, mod, _w, _a in STEPS}
    known.add("__init__.py")
    known.add("main.py")
    known.add("context.py")
    if os.path.isdir(STEPS_DIR):
        for fn in sorted(os.listdir(STEPS_DIR)):
            if not fn.endswith(".py") or fn in known:
                continue
            if fn.startswith("step"):
                problems.append(
                    f"目录里有清单未登记的节点文件：{fn}（若是有意新增，"
                    f"请同步 gui/chain.py 与 steps/main.py 的 CHAIN）")

    # 与 main.py 的 CHAIN 比对
    problems.extend(_verify_main_chain())
    return problems


def _verify_main_chain():
    """轻量解析 main.py 的 CHAIN —— 用 ast，不用 import（import 会执行代码）。"""
    import ast

    path = os.path.join(STEPS_DIR, "main.py")
    if not os.path.isfile(path):
        return [f"找不到主控 {rel(path)}"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (SyntaxError, OSError) as e:
        # 主控语法坏了：这不是 GUI 的错，但要如实报出来
        return [f"主控 main.py 无法解析（{type(e).__name__}）—— 节点链条以本清单为准"]

    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CHAIN":
                    try:
                        found = [tuple(ast.literal_eval(e)) for e in node.value.elts]
                    except (ValueError, AttributeError):
                        pass

    if found is None:
        return ["主控 main.py 里没找到可解析的 CHAIN 定义"]

    mine = [(sid, mod) for sid, _n, mod, _w, _a in STEPS]
    theirs = [(c[0], c[1]) for c in found if len(c) >= 2]
    if mine != theirs:
        lines = ["gui/chain.py 与 steps/main.py 的 CHAIN **不一致**："]
        lines.append(f"    gui/chain.py      : {mine}")
        lines.append(f"    steps/main.py     : {theirs}")
        lines.append("    => 两处都要改。界面上显示的步骤以 gui/chain.py 为准。")
        return ["\n".join(lines)]
    return []


def default_run_root():
    """运行目录的根（与 steps/context.py 的 DEFAULT_RUN_ROOT 一致）。"""
    return os.path.join(ROOT, "logs", "runs")


def latest_run_dir():
    """最近一次运行目录；没有则 None。按 mtime 取最新。"""
    root = default_run_root()
    if not os.path.isdir(root):
        return None
    cands = [os.path.join(root, d) for d in os.listdir(root)
             if os.path.isdir(os.path.join(root, d))]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)
