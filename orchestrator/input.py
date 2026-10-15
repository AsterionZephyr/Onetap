"""orchestrator.input — 真实光标动作与动作前置关

本框架只用真实光标（ADR 0001）。真实光标有三个硬性后果：

  1. **窗口必须在前台**（INV-8）。失焦时 ok-ww 的 sleep() 没有出口，会**静默挂起**，
     症状是「点了毫无反应，且没有任何报错」（FRAMEWORK §2.4）。
  2. **每次点击前必须重新判定前台**：点击会把焦点交给遮挡在上的窗口（实测五）。
  3. **还要判定目标坐标处最顶层的窗口是 ok-ww**（INV-23）——「在前台」不足以
     保证该坐标没被覆盖。

`ensure_foreground` 实现「无条件抢」（Q4 决策）；`guarded_click` 实现动作前置关。
"""

import time

from . import win32
from .errors import GuardFailure

FOREGROUND_TRIES = 10        # 抢前台的尝试次数
FOREGROUND_INTERVAL = 0.4    # 每次间隔（秒）


def ensure_foreground(hwnd, tries=FOREGROUND_TRIES, interval=FOREGROUND_INTERVAL,
                      log=None):
    """把 ok-ww 抢到前台并**验证**。

    步骤（顺序不能换）：
      1. ShowWindow(SW_RESTORE) —— 防最小化（INV-22）
      2. SetForegroundWindow
      3. 校验 GetForegroundWindow() == hwnd
      4. 校验 rect 不是最小化哨兵且尺寸合理

    返回 window_state。失败抛 GuardFailure。
    """
    for attempt in range(1, tries + 1):
        state = win32.window_state(hwnd)
        if state is None:
            raise GuardFailure("INV-12", "窗口已销毁，无法置前台")

        if win32.is_iconic_sentinel(state["left"], state["top"]) or \
                state["width"] < 100 or state["height"] < 100:
            win32.restore_window(hwnd)
            time.sleep(0.5)
            state = win32.window_state(hwnd)
            if state is None or win32.is_iconic_sentinel(state["left"], state["top"]):
                if log:
                    log(f"  置前台 attempt {attempt}: SW_RESTORE 未奏效，重试")
                time.sleep(interval)
                continue

        if state["foreground"]:
            return state

        win32.set_foreground(hwnd)
        time.sleep(0.45)
        state = win32.window_state(hwnd)
        if state and state["foreground"]:
            if log:
                log(f"  置前台成功（第 {attempt} 次尝试）")
            return state

        if log:
            log(f"  置前台 attempt {attempt}: 未取得前台，重试")
        time.sleep(interval)

    raise GuardFailure(
        "INV-8",
        f"连续 {tries} 次未能把 ok-ww 置前台 —— 真实光标点击会落到别处，"
        f"且 ok-ww 会静默挂起。请让开鼠标或关闭遮挡窗口后重试")


def assert_top_window(hwnd, screen_x, screen_y):
    """INV-23：目标屏幕坐标处最顶层的窗口必须是 ok-ww。"""
    top = win32.top_window_at(screen_x, screen_y)
    if top != hwnd:
        raise GuardFailure(
            "INV-23",
            f"目标屏幕坐标 ({screen_x},{screen_y}) 处最顶层窗口是 {top}，"
            f"不是 ok-ww({hwnd}) —— 点击会落到别的程序上")


def guarded_click(hwnd, screen_x, screen_y, dry_run=False, log=None):
    """动作前置关 + 真实光标单击。

    前置关（顺序）：
      1. 屏幕坐标在屏内
      2. 每次点击前**重新判定**前台（INV-8）
      3. 目标坐标处最顶层为 ok-ww（INV-23）

    dry_run=True 时只做前置关，不移动光标 —— 这正是 `--dry-run` 能自证的原因。
    """
    sw, sh = win32.screen_size()
    if not (0 <= screen_x < sw and 0 <= screen_y < sh):
        raise GuardFailure(
            "INV-23", f"点击坐标 ({screen_x},{screen_y}) 越出屏幕 {sw}x{sh}")

    ensure_foreground(hwnd, log=log)
    assert_top_window(hwnd, screen_x, screen_y)

    if dry_run:
        if log:
            log(f"  [DRY RUN] 前置关全过，未点击 ({screen_x},{screen_y})")
        return False

    if log:
        log(f"  点击 ({screen_x},{screen_y})")
    win32.click(screen_x, screen_y)
    return True
