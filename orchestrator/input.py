"""orchestrator.input — 真实光标动作与动作前置关

本框架只用真实光标（ADR 0001）。真实光标有三个硬性后果：

  1. **窗口必须在前台**（INV-8）。失焦时目标程序的 sleep() 没有出口，会**静默挂起**，
     症状是「点了毫无反应，且没有任何报错」（FRAMEWORK §2.4）。
  2. **每次点击前必须重新判定前台**：点击会把焦点交给遮挡在上的窗口（实测五）。
  3. **还要判定目标坐标处最顶层的窗口是目标程序**（INV-23）——「在前台」不足以
     保证该坐标没被覆盖。

`ensure_foreground` 实现「无条件抢」（Q4 决策）；`guarded_click` 实现动作前置关。

⚠️ **FAULT #35**：`ensure_foreground` 抢前台有三条通道，**前两条是 API，最后一条是
真实点击**。游戏窗口（`UnrealWindow`）占住前台时，API 两条**永远失败**（重试无用，
最小化游戏也不释放），只有**在窗口体上真实点击一次**才拿得回来。
详见 `_click_to_activate` 的 docstring。
"""

import time

from . import win32
from .errors import GuardFailure

FOREGROUND_TRIES = 10        # 抢前台的尝试次数
FOREGROUND_INTERVAL = 0.4    # 每次间隔（秒）


ACTIVATE_INSET = 6           # 候选点离窗口边缘的最小距离（像素）
ACTIVATE_GRID_X = 5          # 候选网格列数
ACTIVATE_GRID_Y = 4          # 候选网格行数


def _activation_candidates(st):
    """给「真实点击夺取激活」生成候选屏幕坐标，**首选点在最前**。

    首选点 = 窗口体左 1/5、顶部 18px（标题栏区域），理由见 `_click_to_activate`。
    之后是 5×4 网格 + 四条窄边带，用于**绕开遮挡** —— 实测（2026-10-19 03:2x）
    MaaEnd 被它自己拉起的「鹰角启动器」盖住 95%，只剩右侧 24px、底部 87px 的缝，
    固定点数在左上角 ⇒ 点进了启动器，激活永远拿不到。
    """
    left, top, w, h = st["left"], st["top"], st["width"], st["height"]
    pts = [(left + max(20, w // 5), top + min(18, h // 8))]
    inset = ACTIVATE_INSET
    xs = [left + inset + (w - 2 * inset) * i // (ACTIVATE_GRID_X - 1)
          for i in range(ACTIVATE_GRID_X)]
    ys = [top + inset + (h - 2 * inset) * j // (ACTIVATE_GRID_Y - 1)
          for j in range(ACTIVATE_GRID_Y)]
    for y in ys:
        for x in xs:
            pts.append((x, y))
    # 窄边带（遮挡窗口几乎盖满时唯一能点的去处）
    for y in ys + [top + h - inset, top + h // 2]:
        pts.append((left + w - inset, y))
        pts.append((left + inset, y))
    for x in xs:
        pts.append((x, top + h - inset))
    seen = set()
    out = []
    for p in pts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _click_to_activate(hwnd, log=None):
    """最后一手：**在目标窗口体上真实点击一次**，用系统认可的用户输入夺取前台。

    ⚠️ FAULT #35（实测 2026-10-17）：游戏窗口（`UnrealWindow`，异环）占住前台后，
    `set_foreground` 的三手段（裸调 / AttachThreadInput / ALT 抖动）**全部无效且
    永不成功** —— 实测连续 10 次全败；把游戏**最小化也不释放**前台。
    但**真实鼠标点击目标窗口体一次**即可立即夺回，且随后 `ensure_foreground`
    立即通过（实测 3/3）。

    ⚠️ FAULT #36（实测 2026-10-19 03:20，MaaEnd）：「点目标窗口体」不等于
    「点哪个点都行」。MaaEnd 跑完后它自己拉起的**鹰角启动器**（Qt，
    `Qt5158QWindowIcon`）跳到前台，盖住 MaaEnd 约 95%（启动器 1312×754 在
    (624,323)，MaaEnd 1201×826 在 (759,338)），且该启动器**线程不响应**
    ⇒ `SetForegroundWindow` 从此**永久失败**（不是「等 10 秒就好」，重跑两次都败）。
    此时固定点（左上 1/5、顶部 18px）**正落在启动器上**：真实点击把激活交给了
    启动器，MaaEnd 一次也没拿到前台，框架报 INV-8 —— 而 INV-23 的本意正是
    「不许点到别的程序上」。修法三步：
      1. `win32.raise_window(hwnd)` 先把目标抬到 Z 序最上层（不改焦点）；
      2. 候选点按 `top_window_at(x,y) == hwnd` **逐个验证**，跳过被遮挡的点；
      3. 一个都验不过 ⇒ **不点**（点了就是操作别的程序），如实报遮挡者。

    点哪里（首选点）：窗口**顶部**（标题栏区域）横坐标偏左 1/5 处。理由：
      · 避开右上角的最小化/最大化/关闭按钮；
      · 避开窗口主体里可能存在的可交互控件（点击它会产生副作用）；
      · 标题栏拖动需要按下+移动，单纯单击不会拖动窗口。
    首选点验不过时退到 `_activation_candidates` 的网格与窄边带。
    """
    st = win32.window_state(hwnd)
    if st is None:
        return False
    if st["width"] < 100 or st["height"] < 40:
        return False

    if win32.raise_window(hwnd):
        time.sleep(0.15)
        st = win32.window_state(hwnd) or st

    sw, sh = win32.screen_size()
    cover = None
    for x, y in _activation_candidates(st):
        if not (0 <= x < sw and 0 <= y < sh):
            continue
        top_win = win32.top_window_at(x, y)
        if top_win != hwnd:
            if cover is None:
                cover = (top_win, x, y)
            continue
        if log:
            log(f"  置前台 API 全部失效 —— 改用在窗口体上真实点击 ({x},{y}) 夺取激活")
        try:
            win32.click(x, y)
        except Exception:                                 # noqa: BLE001
            return False
        time.sleep(0.6)
        st2 = win32.window_state(hwnd)
        return bool(st2 and st2["foreground"])

    if log and cover:
        log(f"  ⚠ 目标窗口整块被其他窗口遮挡（{cover[0]} 在 ({cover[1]},{cover[2]})），"
            f"不做点击 —— 点了就是操作别的程序（INV-23）")
    return False


def covering_window(hwnd):
    """目标窗口当前是否被**别的顶层窗口**遮住；是则返回 (hwnd, 标题) 供报错用。

    只用于诊断信息：探测目标 rect 的 5 个代表点，返回第一个不属于目标的顶层窗口。
    """
    st = win32.window_state(hwnd)
    if st is None:
        return None
    left, top, w, h = st["left"], st["top"], st["width"], st["height"]
    probes = [(left + w // 2, top + h // 2),
              (left + max(20, w // 5), top + min(18, h // 8)),
              (left + w - ACTIVATE_INSET, top + h // 2),
              (left + w // 2, top + h - ACTIVATE_INSET),
              (left + ACTIVATE_INSET, top + ACTIVATE_INSET)]
    for x, y in probes:
        other = win32.top_window_at(x, y)
        if other and other != hwnd:
            return other, win32.get_window_text(other)
    return None


def ensure_foreground(hwnd, tries=FOREGROUND_TRIES, interval=FOREGROUND_INTERVAL,
                      log=None):
    """把目标程序抢到前台并**验证**。

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

    # --- 最后一手：真实点击夺取激活（FAULT #35）---
    # API 三手段全败时，HANDOFF §2.2 第 5 条的「真实鼠标点击窗口体」仍然有效。
    # 放在循环**之外**：它不是「再试一次 API」，而是换一条通道，试多次无意义。
    if _click_to_activate(hwnd, log=log):
        st = win32.window_state(hwnd)
        if st and st["foreground"]:
            if log:
                log("  置前台成功（改用真实点击夺取激活）")
            return st

    cover = covering_window(hwnd)
    if cover:
        extra = (f"；目标窗口当前被别的窗口遮挡：hwnd={cover[0]} 标题={cover[1]!r} "
                 f"—— 先关掉/最小化它（INV-23 不允许点别的程序）")
    else:
        extra = "；目标窗口未被遮挡，可能是别的程序正持有前台且不响应"
    raise GuardFailure(
        "INV-8",
        f"连续 {tries} 次未能把目标程序置前台，且真实点击窗口体也未能夺取激活 —— "
        f"真实光标点击会落到别处，且它会静默挂起{extra}")


def assert_top_window(hwnd, screen_x, screen_y):
    """INV-23：目标屏幕坐标处最顶层的窗口必须是目标程序。"""
    top = win32.top_window_at(screen_x, screen_y)
    if top != hwnd:
        raise GuardFailure(
            "INV-23",
            f"目标屏幕坐标 ({screen_x},{screen_y}) 处最顶层窗口是 {top}，"
            f"不是目标窗口({hwnd}) —— 点击会落到别的程序上")


def guarded_click(hwnd, screen_x, screen_y, dry_run=False, log=None):
    """动作前置关 + 真实光标单击。

    前置关（顺序）：
      1. 屏幕坐标在屏内
      2. 每次点击前**重新判定**前台（INV-8）
      3. 目标坐标处最顶层为目标程序（INV-23）

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