"""orchestrator.state — 任务状态判定（框架必须自己做，不能指望 ok-ww）

ok-ww 有两种**完全不同**的终止行为（HANDOFF §6、FRAMEWORK §5.8 实测十三）：

  正常完成  自行退出。日志里连续出现
            `Daily Task Completed` → `Successfully Executed Task, Exiting Game and App!`
            → 杀游戏 → 约 5 秒后 ok-ww 开始关自己 → `quit app`。
  等待条件  永不超时、无限等待。计时器**冻结**（实测冻结在 1m32s），错误栏显示原因。

**像素上的陷阱**：横幅 `已完成：📅 每日任务 已运行: 0h 1m 32s` 在**两种情况下文案完全相同**。
故：

  完成帧 = 同一帧内同时含「已完成」横幅 **与**「退出通知」。

退出通知「成功执行任务, 正在退出游戏和App!」只在正常完成时出现，是唯一的区分图元（Q7 决策）。
"""

import re

import numpy as np

from . import match
from .errors import GuardFailure

# 面板 / 横幅所在区域。进度面板出现时横幅在窗口顶部约 y=60..110 处；
# 每帧重新定位，本模块只提供「候选区域」，不假设固定坐标（INV-25）。
BANNER_BAND = (40, 140)

# 计时器形如 `0h 1m 32s`
TIMER_RE = re.compile(r"(\d+)\s*h\s*(\d+)\s*m\s*(\d+)\s*s")


class ProgressPanel:
    """从一帧里读出的进度面板信息。字段缺失一律为 None，不臆测。"""

    def __init__(self):
        self.banner_present = False     # 是否出现「已完成」横幅样式
        self.timer_seconds = None       # 运行时长（秒），读不到为 None
        self.exit_notice = None         # 退出通知的匹配分数，None 表示未检出
        self.brightness = 0.0           # 顶部条带亮度占比（诊断用）

    def __repr__(self):
        return (f"ProgressPanel(banner={self.banner_present}, "
                f"timer={self.timer_seconds}, exit_notice={self.exit_notice})")


def band_brightness(frame_rgb, band=BANNER_BAND):
    """顶部条带的亮像素占比。进度面板出现时它显著升高（约 0.15 -> 0.55）。"""
    y0, y1 = band
    y1 = min(y1, frame_rgb.shape[0])
    if y1 <= y0:
        return 0.0
    g = match.to_gray(frame_rgb[y0:y1])
    return float((g > 100).mean())


def read_progress(frame_rgb, exit_notice_tpl=None):
    """读一帧的进度面板状态。

    exit_notice_tpl：退出通知的图像资产。模板匹配命中即认为通知可见。
      —— 这是「完成帧」判据的一半。
    """
    p = ProgressPanel()
    p.brightness = band_brightness(frame_rgb)

    # 横幅存在性：用顶部条带亮度 + 高度阈值作代理判据。
    # 真正的文案判读需要 OCR，本框架不引入 OCR（环境无 cv2/onnxocr 依赖），
    # 因此「已完成」文案本身**不作为**判据，只作诊断输出。
    p.banner_present = p.brightness > 0.30

    if exit_notice_tpl is not None:
        res = match.match_best(frame_rgb, exit_notice_tpl)
        if res is not None:
            score, _x, _y = res
            if score >= match.ACCEPT:
                p.exit_notice = score

    return p


def is_completion_frame(frame_rgb, exit_notice_tpl):
    """完成帧判据（Q7 决策，已由用户确认）。

    **主判据：同一帧内 横幅 + 退出通知。**

    不做 OCR，「横幅」用顶部条带亮度代理，「退出通知」用图像资产匹配。
    两者同时成立才算完成帧。

    注意判据的保守性：宁可漏判（退回「超时」分支），不可误判
    —— 误判会把一次卡死当成成功，而框架随后的行为（不再杀进程）完全不同。
    """
    if exit_notice_tpl is None:
        return False, "未登记退出通知资产，无法判定完成帧"

    p = read_progress(frame_rgb, exit_notice_tpl)
    if not p.banner_present:
        return False, f"未见横幅（顶部亮度 {p.brightness:.3f}）"
    if p.exit_notice is None:
        return False, f"未见退出通知（顶部亮度 {p.brightness:.3f}）"

    return True, (f"完成帧：横幅亮度 {p.brightness:.3f} + "
                  f"退出通知 score={p.exit_notice:.4f}")


class FreezeDetector:
    """计时器冻结检测 —— 判定**等待状态**（ok-ww 永不超时的那条路）。

    判据：计时器文本连续 `freeze_seconds` 秒不变。

    用户决策：N = 180 秒。
    """

    def __init__(self, freeze_seconds=180.0):
        self.freeze_seconds = freeze_seconds
        self._last_timer = None
        self._last_change_at = None

    def update(self, frame_rgb, now):
        """喂一帧，返回 (frozen: bool, detail: str)。

        只用一个**廉价**的指纹代表计时器区域：顶部条带的灰度采样和。
        真正的 OCR 不理解也不需要 —— 冻结态的特征是「这块像素完全不动」。
        """
        y0, y1 = BANNER_BAND
        y1 = min(y1, frame_rgb.shape[0])
        band = match.to_gray(frame_rgb[y0:y1])
        fingerprint = float(band[::3, ::3].sum())

        if self._last_timer is None:
            self._last_timer = fingerprint
            self._last_change_at = now
            return False, "首次采样"

        # 阈值取「采样点数」的千分之一量级，滤掉亚像素抖动
        if abs(fingerprint - self._last_timer) > max(1.0, abs(self._last_timer) * 1e-4):
            self._last_timer = fingerprint
            self._last_change_at = now
            return False, "计时器区域有变化"

        frozen_for = now - self._last_change_at
        if frozen_for >= self.freeze_seconds:
            return True, (f"顶部条带已 {frozen_for:.0f} 秒无变化 "
                          f"(>= {self.freeze_seconds:.0f}s) —— 疑似等待状态")
        return False, f"已静止 {frozen_for:.0f} 秒（阈值 {self.freeze_seconds:.0f}s）"


def parse_timer(text):
    """从文本里解析 `0h 1m 32s` 形式的运行时长，返回秒数或 None。"""
    m = TIMER_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
