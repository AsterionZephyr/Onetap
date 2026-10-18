"""节点 8 的通用助手：落盘取证、画面变化判定、result -> 状态码映射。

**为什么单独一个模块**（docs/adr/0003 阶段二）：

    这三件事是**所有程序共用**的机制，但它们的调用方分散在：
        ok-ww / ok-nte 的节点 8 骨架   -> steps/step8_run_task.py
        MaaEnd 的专属实现             -> apps/zmd.py
    若把它们留在 step8 里，apps/zmd.py 就必须 import step8 —— 既是循环 import
    （step8 -> apps.zmd -> step8），也会让「改 MaaEnd 波及 ww/nte」重新长回来。

    故下沉到这里。step8 与 apps/*.py 都从这里 import，谁都不 import 谁。
    本模块**不认识任何具体程序**（不出现 "ww"/"nte"/"zmd"）。
"""

import os

# 画面「有变化」的平均绝对差阈值（原在 orchestrator.py，随 frame_changed 一起下沉）。
# ⚠️ 不能反过来 "from .orchestrator import CHANGE_THRESHOLD"：apps/zmd.py 要 import
#    本模块，而 orchestrator.py 会 import match，match 又会 import apps.zmd ——
#    实测直接 ImportError: cannot import name 'ZMD_BOTTOM_FRAC' from partially
#    initialized module。故阈值落在本叶子模块，由 orchestrator.py 反向取。
CHANGE_THRESHOLD = 0.5

# FAULT #23：整帧统计量对**局部**变化不敏感（ok-nte 的 toast 只有 0.153）。
# 判据因此三分：整帧（大面积渐变）/ 最大块（局部响应）/ 变化像素占比（兜底）。
#
# 实测样本：最大块差 3.20（块 行0列3，就是那条 toast）；变化>10 的像素 0.5%。
CLICK_BLOCK_ROWS = 8          # 分块网格行数
CLICK_BLOCK_COLS = 8          # 分块网格列数
CLICK_BLOCK_MIN = 2.0         # 任一块平均差 >= 此值即认为「有局部变化」
CLICK_PIXEL_DELTA = 10        # 单像素差超过此值才算「真的变了」
CLICK_PIXEL_FRAC = 0.002      # 变化像素占比 >= 0.2% 即认为「有变化」（实测 0.5%）


def shot(state, frame, tag, log=None):
    """把当前帧落盘到本次运行的 shots/ 下，并登记到 state。"""
    from PIL import Image
    path = state.shot_path(tag)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(frame.rgb if hasattr(frame, "rgb") else frame).save(path)
    state.add_shot("8", path)
    if log:
        log(f"  [落盘] {os.path.relpath(path, state.run_dir)}")
    return path


def frame_changed(before, after, log=None):
    """判断点击后画面是否真的变了；返回 (changed, 说明串)。

    **三个判据任一成立即算变化**（FAULT #23）：

    1. 整帧平均差 >= CHANGE_THRESHOLD —— 原判据，对整页切换（ok-ww 导航）有效；
    2. **任一 8x8 块**的平均差 >= CLICK_BLOCK_MIN —— 抓局部响应
       （ok-nte 的 toast / 按钮按下态就靠这条）；
    3. 变化像素（|Δ| > CLICK_PIXEL_DELTA）占比 >= CLICK_PIXEL_FRAC —— 兜底。

    ⚠️ 为什么不能只留第 2 条：整块阈值对「大面积但幅度小的渐变」不敏感，
    而第 1 条正好覆盖那种情形。三条**互补**，不是冗余。

    ⚠️ 返回值是 **tuple**（changed, why），不是 bool。调用方写 `if changed is True`
    永远不成立（实测踩过：MaaEnd 的弱证据分支因此永久走不到）。
    """
    b = before.astype("int16")
    a = after.astype("int16")
    if b.shape != a.shape:
        # 尺寸变了本身就是「画面变了」（窗口被重建/缩放）
        return True, f"帧尺寸改变 {b.shape} -> {a.shape}"

    d = abs(a - b).mean(axis=2) if b.ndim == 3 else abs(a - b).astype("float64")
    whole = float(d.mean())

    H, W = d.shape
    worst = 0.0
    worst_rc = (0, 0)
    for i in range(CLICK_BLOCK_ROWS):
        y0, y1 = i * H // CLICK_BLOCK_ROWS, (i + 1) * H // CLICK_BLOCK_ROWS
        for j in range(CLICK_BLOCK_COLS):
            x0, x1 = j * W // CLICK_BLOCK_COLS, (j + 1) * W // CLICK_BLOCK_COLS
            m = float(d[y0:y1, x0:x1].mean())
            if m > worst:
                worst, worst_rc = m, (i, j)

    frac = float((d > CLICK_PIXEL_DELTA).mean())

    why = (f"整帧={whole:.2f}/{CHANGE_THRESHOLD}"
           f" 最大块={worst:.2f}@块{worst_rc}/{CLICK_BLOCK_MIN}"
           f" 变化像素={frac * 100:.2f}%/{CLICK_PIXEL_FRAC * 100:.1f}%")
    if log:
        log(f"  点击后：{why}")

    if whole >= CHANGE_THRESHOLD:
        return True, why
    if worst >= CLICK_BLOCK_MIN:
        return True, why
    if frac >= CLICK_PIXEL_FRAC:
        return True, why
    return False, why


def finish(state, result, detail, frame_path, log):
    """result -> 状态码（**唯一一处**映射，避免各程序路径与主流程漂移）。

    "unknown" 映射为 "skipped" 是刻意的：context.run_step 只把 ok/skipped
    当非失败（退出码 0、链条继续）。unknown 时目标程序多半已经退出，
    清理无从下手；用退出码把一次正常夜间流程标红是误导，交由**人**看日志裁决。
    """
    log(f"\n[结果] {result}：{detail}")
    state.set("result", result)
    state.set("result_detail", detail)
    status = {"completed": "ok", "timeout": "timeout", "failed": "failed",
              "unknown": "skipped",
              # FAULT #30：「停住了」不是超时 —— 它是**确定**的失败
              "stalled": "failed"}.get(result, "failed")
    return status, {"result": result, "detail": detail,
                    "completion_frame": frame_path}, f"{result}：{detail}"


def grab(state, strict=True, log=None):
    """抓一帧（每次都用**重新发现**的 hwnd，遵守 INV-14）。

    原实现是 step8 的模块级函数，2026-10-19 下沉到共用助手（三个程序都用它）。
    惰性 import：steps.context 依赖抓帧/校验链，模块级 import 会成环。
    """
    from . import capture as capture_mod
    from .steps import context

    hwnd = context.require_hwnd(state, log=None)
    f = capture_mod.grab_frame(hwnd, strict_content=strict)
    state.set("hwnd", hwnd)
    return hwnd, f


# ------------------------------------------------------------ 8a 导航
