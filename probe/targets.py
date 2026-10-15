"""targets.py — 程序配置（编排层的唯一"因程序而异"之处）

设计原则（见 HANDOFF.md §8.1）：
  差异全部落在配置里；window / capture / match / input 四个模块两程序共用。

每个 target 提供：
  - exe / title_regex          : 如何发现并启动
  - nav_sidebar_y              : 任务页在侧栏的 y 位置
  - anchors                    : identity（身份校验）/ page（页面锚点）/ action（动作元素）
  - detect_state(frame)        : 由一帧判定当前状态
  - is_done(frame, procs)      : 判定"是否已完成"
"""

from pathlib import Path

import numpy as np
from PIL import Image

from template_probe import match_template
from nte_main import all_hits

TPL = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")

# 匹配阈值（见 FRAMEWORK §3.4）
ACCEPT = 0.90      # >= 接受
WARN = 0.85        # 0.85~0.90 需交叉验证
REJECT = 0.85      # < 拒绝


def load(name):
    return np.array(Image.open(TPL / name).convert("RGB"))


def score(frame, tpl):
    s, x, y = match_template(frame, tpl)
    return s, x, y


def unique(frame, tpl, thresh=ACCEPT, min_dist=None):
    """唯一性检查（INV-24/27）。返回 (ok, hits)。"""
    th, tw, _ = tpl.shape
    md = min_dist if min_dist is not None else max(20, tw // 2)
    hits = all_hits(frame, tpl, thresh, md)
    return (len(hits) == 1, hits)


# ---------------------------------------------------------------- ok-ww

WW_TITLE = r"OK-WW"
# ⚠️ 身份锚点必须**页面无关且唯一**。
#    实测踩坑：曾用 1_ww.png（侧栏 ▶ 图标）当身份锚点 ——
#    它在窗口尺寸 1458x800（本轮实测出现的**最小尺寸**）下只得 **0.3962**，
#    因为该尺寸下侧栏图标更小、位置不同（DPI/缩放相关），导致就绪等待 180s 超时。
#    改用 **3_ww_menu.png（左上 ☰ 菜单图标）**：实测 1.0000 且唯一，页面无关。
#    （与 ok-nte 的 4_nte_menu.png 同一策略）
WW_IDENTITY = load("3_ww_menu.png")     # ☰ 菜单图标
WW_SIDEBAR = load("1_ww.png")
WW_ROW = load("2_ww.png")
# 页面锚点 = 「日历图标 + 每日任务」四字，**独立资产**（不再从整行切片）。
#   ⚠️ 演进历史：
#      v3.6.7 时代用 `2_ww.png[:, 9:72]`（右边界 72 是按当时 41px 行高估的）。
#      升到 **v3.7.3** 后该切片只得 **0.4851**，且**与窗口尺寸无关**
#      （1458x800 与 1823x1000 得分完全相同）—— 说明是**内容变了**，不是缩放问题。
#      实测新版本「每日任务」行内容块：图标 x=49..104，文字 x=186..541。
#      新锚点取 x=45..250（含图标 + 「每日任务」四字），实测 **1.0000 且唯一**。
#   ⚠️ 切片必须**同时含日历图标**：仅"每日任务"会被「多账号每日任务」子串命中。
WW_PAGE_ANCHOR = load("2_ww_page.png")


def ww_state(frame, procs):
    """ok-ww 状态：读进度面板横幅（运行中 / 已完成）。本项目用按钮/横幅文字判定。"""
    # 简化：以「每日任务」行是否可见 + 进程是否存在判定
    s, _, _ = score(frame, WW_PAGE_ANCHOR)
    return {"anchor_score": round(s, 4), "pythonw": bool(procs.get("pythonw"))}


# ---------------------------------------------------------------- ok-nte

NTE_TITLE = r"ok-nte"
# ⚠️ 身份锚点必须**在任何页面都能匹配到且唯一**。
#    实测踩坑（两次）：
#      1. 曾用 3_nte_daily（「日常任务」文字）当身份锚点 ——
#         程序启动停在「关于」页，得 0.4224 被误判为"不是该程序"。
#      2. 改用 1_nte（原侧栏图标）—— 在新版 UI 上只得 0.5096，且**有 2 个候选**。
#    最终采用 **4_nte_menu.png（左上 ☰ 菜单图标）**：
#      实测在任何页面均 1.0000 且**唯一**，且属于窗口固定元素。
NTE_IDENTITY = load("4_nte_menu.png")    # ☰ 菜单图标（页面无关，唯一）
NTE_PAGE = load("3_nte_daily.png")       # 「日常任务」文字（页面锚点）
NTE_ACTION = load("2_nte.png")           # 「▶ 开始」按钮


def nte_state(frame, procs):
    """ok-nte 状态：看「开始」按钮是否还在。"""
    s_page, _, _ = score(frame, NTE_PAGE)
    s_btn, bx, by = score(frame, NTE_ACTION)
    th, tw, _ = NTE_ACTION.shape
    return {
        "page_score": round(s_page, 4),
        "action_score": round(s_btn, 4),
        "running": s_btn < ACCEPT,            # 按钮不在 = 运行中
        "action_center": (bx + tw // 2, by + th // 2) if s_btn >= ACCEPT else None,
        "pythonw": bool(procs.get("pythonw")),
    }


TARGETS = {
    "ok-ww": {
        "exe": r"E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe",
        "cwd": r"E:\TOOLS\ScriptsGames\ok-ww",
        "title_regex": WW_TITLE,
        "window_size": (1823, 1000),   # 资产采集尺寸
        # ⚠️ 侧栏**第几项**比绝对 y 稳健 —— 侧栏行距随窗口高度缩放
        #    （实测 1823x1000 下任务项 y≈230；1458x800 下 y≈183）。
        #    故改用"内容簇序号"（0-based）：任务 = 第 3 项 => index 2。
        "nav_sidebar_index": 2,
        "nav_sidebar_y": 230,           # 仅作回退/参考
        "anchors": {
            "identity": WW_IDENTITY,
            "page": WW_PAGE_ANCHOR,
            "action": None,             # 按钮由行结构扫描得出（见 run_daily2.py）
        },
        "state_fn": ww_state,
        # 终态判据模块（见 COMPLETION-VERDICT.md / Q2）
        "verdict_module": "ww_verdict",
        # ok-ww 正常完成后自行退出
        "done_when": "process_gone",
    },
    "ok-nte": {
        "exe": r"E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe",
        "cwd": r"E:\TOOLS\ScriptsGames\ok-nte",
        "title_regex": NTE_TITLE,
        "window_size": (1875, 1250),  # 资产采集尺寸（v1.4.8）
        # 侧栏第几项（0-based）。ok-nte 任务项实测 y≈329（1520x1020）。
        "nav_sidebar_index": 3,
        "nav_sidebar_y": 329,
        "anchors": {
            "identity": NTE_IDENTITY,
            "page": NTE_PAGE,
            # ⚠️ v1.4.8 起改为**行结构扫描**：UI 由"单行日常任务 + 右下角一个开始"
            #    变为**逐任务行**（每行一个「开始」，实测 9 个同款按钮 => 模板必然歧义）。
            #    与 ok-ww 同构，故 action=None 表示"由扫描得出"。
            "action": None,
        },
        "action_scan": "find_nte_action",
        "state_fn": nte_state,
        # ok-nte 的日志结构与 ok-ww **不同**（无阶段序列，用终止标记）：
        #   `TaskExecutor:Successfully Executed Task, Exiting Game and App!`
        "verdict_module": "nte_verdict",
        # ok-nte 正常完成后同样自行退出（见 OK-NTE-ADAPTATION §6）
        "done_when": "process_gone",
    },
}
# 编排顺序（用户指定：ok-ww 先运行）
ORDER = ["ok-ww", "ok-nte"]
