"""orchestrator.capture — 抓帧与帧校验

三条不变量在这里拦截（HISTORY A.4）：

  INV-1   帧尺寸必须等于当次窗口 rect。不一致时**绝不用该帧算坐标**。
  INV-12  窗口「可见」不等于「屏幕上真的有」。
  INV-13  帧全黑即中止（PrintWindow 对 Qt 自绘返回全黑，故只用屏幕抓图）。
  INV-17  越界抓帧会**静默产出全黑帧**，故抓前先校验坐标在屏内。

另需注意（INV-18）：内容校验**只能筛出全黑**，不能判定「抓到的是 ok-ww」。
身份确认是 match.verify_identity 的职责，不在本模块。
"""

import numpy as np

from . import win32
from .errors import GuardFailure

# 帧内容判据
MIN_MEAN_SUM = 15          # 均值 RGB 之和低于此值视为全黑
MIN_DISTINCT_COLORS = 5    # 采样色彩种类数低于此值视为可疑

BGRA_TO_RGB = [2, 1, 0]


def frame_stats(data, w, h, max_samples=4000):
    """帧内容统计。用于 INV-13 的「非全黑」判定。"""
    arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
    bgr = arr[:, :, :3]
    n = w * h
    step = max(1, n // max_samples)
    flat = bgr.reshape(-1, 3)[::step]
    quant = (flat >> 3).astype(np.int32)
    uniq = np.unique(quant[:, 0] * 1024 + quant[:, 1] * 32 + quant[:, 2])
    return {
        "mean_rgb": tuple(int(v) for v in bgr.reshape(-1, 3).mean(axis=0)[::-1]),
        "distinct_colors_sampled": int(uniq.size),
        "sampled": int(flat.shape[0]),
    }


class Frame:
    """一帧图像，携带它来自哪个窗口、哪次窗口 rect。

    帧一旦构造成功，就保证：尺寸 == 抓取时的窗口 rect，且内容非全黑。
    """

    def __init__(self, rgb, rect, size, stats):
        self.rgb = rgb                # numpy (h, w, 3) RGB
        self.rect = rect              # (left, top, right, bottom)
        self.width = size[0]
        self.height = size[1]
        self.stats = stats            # frame_stats 的返回

    @property
    def left(self):
        return self.rect[0]

    @property
    def top(self):
        return self.rect[1]

    def screen_xy(self, cx, cy):
        """帧内坐标 -> 屏幕坐标（**只差一个平移**）。

        ⚠️ 为什么不能用 win32.client_to_screen：本框架的帧是**整窗 rect** 的
        BitBlt（含标题栏与边框），而 client 坐标从**客户区**左上角算。
        MaaEnd 实测偏移 (8,1)：同一像素点用 client_to_screen 换算得
        (1567,1131)，真实屏幕位置是 (1559,1130) —— 差 8px，点下去就偏。
        Qt 程序（ok-ww/ok-nte）因为无边框，两者恰好重合，所以这个坑
        **只在接入带标准边框的窗口时**才暴露。

        INV-17 的同类断言：坐标越界时不要静默返回，直接失败。
        """
        if not (0 <= cx < self.width and 0 <= cy < self.height):
            raise GuardFailure(
                "INV-17",
                f"帧内坐标 ({cx},{cy}) 越界（帧 {self.width}x{self.height}）")
        return self.left + int(cx), self.top + int(cy)


def grab_frame(hwnd, expected_state=None, strict_content=True):
    """抓取窗口当前内容，并按 INV-1 / INV-12 / INV-13 / INV-17 校验。

    expected_state: 若给出 win32.window_state 的结果，用于交叉确认 rect 未被换掉。
    strict_content: 是否把「内容可疑」当失败。诊断用途可关掉。
    """
    state = win32.window_state(hwnd)
    if state is None:
        raise GuardFailure("INV-12", "GetWindowRect 失败，窗口可能已销毁")

    left, top, w, h = state["left"], state["top"], state["width"], state["height"]

    # INV-22：置前台成功也可能是最小化哨兵 rect
    if win32.is_iconic_sentinel(left, top) or w < 100 or h < 100:
        raise GuardFailure(
            "INV-22",
            f"窗口 rect 异常（最小化？）rect=({left},{top}) {w}x{h}")

    if expected_state is not None and (left, top, w, h) != (
            expected_state["left"], expected_state["top"],
            expected_state["width"], expected_state["height"]):
        raise GuardFailure(
            "INV-2",
            f"窗口 rect 在两次读取之间变化："
            f"{expected_state['width']}x{expected_state['height']} -> {w}x{h}")

    # INV-17：抓前校验坐标在屏内，否则 BitBlt 会静默给全黑帧
    if not win32.region_on_screen(left, top, w, h):
        raise GuardFailure(
            "INV-17",
            f"抓帧区域越界：({left},{top}) {w}x{h}，屏幕 {win32.screen_size()}")

    got = win32.capture_region(left, top, w, h)
    if got is None:
        raise GuardFailure("INV-13", "BitBlt/GetDIBits 返回失败")

    data, fw, fh = got

    # INV-1：这是第一号不变量 —— 尺寸错了也会点下去，且点歪了不报错
    if (fw, fh) != (w, h):
        raise GuardFailure(
            "INV-1",
            f"帧尺寸 {fw}x{fh} != 窗口 rect {w}x{h}，坐标必然错位")

    stats = frame_stats(data, fw, fh)

    # INV-13 / INV-18：只筛全黑，不判身份
    mean_sum = sum(stats["mean_rgb"])
    if mean_sum < MIN_MEAN_SUM:
        raise GuardFailure(
            "INV-13",
            f"帧几乎全黑（均值 RGB {stats['mean_rgb']}）—— 抓图落空")
    if strict_content and stats["distinct_colors_sampled"] < MIN_DISTINCT_COLORS:
        raise GuardFailure(
            "INV-13",
            f"帧色彩极其单一（{stats['distinct_colors_sampled']} 色）—— 可疑")

    arr = np.frombuffer(data, dtype=np.uint8).reshape(fh, fw, 4)
    rgb = np.ascontiguousarray(arr[:, :, BGRA_TO_RGB])

    return Frame(rgb, (left, top, left + w, top + h), (fw, fh), stats)
