"""MaaEnd（program key = "zmd"）专项模块 —— 定位 + 运行判据。

**为什么单独一个文件**（docs/adr/0003）：
  MaaEnd 与 ok-ww / ok-nte 在每一层都不同构 —— 单层进程（自己持窗口）、
  Tauri 窗口类、单页界面（没有侧栏、任务列表、开始按钮的行结构）、
  完成信号在 Rust 后端日志里而不是画面里。这些差异代码原先散落在
  orchestrator/match.py / orchestrator/verdict.py 三个共用文件里，
  改 MaaEnd 要在别人的文件里动手（反向也成立）—— 一处笔误就会波及
  另外两个程序的定位/判据，且这类波及**不报错**，只给错误结论。

  故每个程序一个模块：本文件承载 MaaEnd 的全部专属逻辑。
  match.py / verdict.py 保留同名 re-export 垫片，旧调用点与
  probe/zmd_*_selfcheck.py 不用改；**新增/修改的逻辑只写在这里**。

⚠️ 本模块**不 import** match / verdict / apps/zmd/nodes/step8_run_task —— 专属逻辑
不许反向依赖共用层；节点 8 模组在文件顶部 import 本模块，反向即环。
"""

import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ... import capture as capture_mod
from ... import input as input_mod
from ... import programs as programs_mod
from ... import window
from ...errors import GuardFailure
from ...frameops import finish, frame_changed, shot
from ...statuses import COMPLETED, FAILED, RUNNING, SUCCESS, TIMEOUT, UNKNOWN

# ==========================================================================
# MaaEnd（MaaEnd.exe，**Tauri + WebView2，非 Qt**）—— 绿色「▶ 开始任务」按钮
# ==========================================================================
#
# 为什么这里既不用截图模板（ok-ww 那套互相关），也不用行结构扫描：
#   1. MaaEnd 是 **Tauri + WebView2**，界面由前端 DOM 渲染，不是 Qt 自绘
#      （对比 INV-10：ok-ww 零子窗口、纯 Qt 自绘）。WebView2 的缩放 / 字体
#      抗锯齿 / 亚像素渲染让同一按钮在不同帧上的像素差异明显；而 INV-34 /
#      INV-38 已经证明「按坐标手工裁剪的截图资产」「固定截图当身份锚点」
#      都会在程序改动或异步加载后失效。
#   2. ok-ww / ok-nte 的任务页是「逐行一个开始按钮」，MaaEnd 只有底部**一个**
#      「▶ 开始任务」；用行扫描反而去找并不存在的行距。
#   ⇒ 改用**结构性特征**：按钮是整块饱和绿实心矩形，并且它是整帧里唯一
#     「够大 + 够宽 + 落在底部带 + 盒内带白色文字」的绿色连通域。
#
# 为什么色判据用**通道差**（g-r、g-b）而不是「RGB 等于 #008B45」：
#   主色实测 RGB(0,139,69)，但按钮边缘有抗锯齿过渡、文字有半透明叠加，
#   逐像素并不全等于主色；而灰/白/浅绿背景三通道接近、通道差≈0，天然被
#   通道差拒绝。要求绝对相等会在 DPI/主题变化时整片漏检，且漏检**不报错**。
#
# 为什么几何判据用比例 / 量级而不是参考帧（1201x826）的绝对坐标：
#   INV-2 / INV-39：窗口尺寸会变，绝对坐标必然在某个尺寸上错。故「按钮在
#   底部」写成 y0 >= 0.85*H，唯一性写成面积比值。宽高仍给像素区间，因为
#   它由字号与内边距决定（实测 112x40）；区间故意放宽到 0.71x~1.96x 宽、
#   0.70x~1.60x 高。⚠️ **多帧多尺寸尚未复核** —— 按 INV-35 的教训，单一
#   尺寸的观测只能记为「现象」，不能断言「布局常量」。
#
# 实测（2026-10-18，1201x826 整窗 BitBlt 帧，参考图 logs/probe/zmd_full.png）：
#   全帧绿像素约 8013 个，绿色连通域 90 个，其中：
#     按钮   cells=275  box=(744,772,856,812) w=112 h=40  盒内白占比 0.149
#     胶囊   cells=121  box=(1032,132,1116,156) w=84  h=24 ← 高 24 太矮、且不在底部带
#     勾选点 cells=23   box=(64,164,84,184)     w=20  h=20 ← 格数 23 远小于 90
#   ⇒ 四道闸门（格数 / 宽高区间 / 底部带 / 白字占比）把干扰项全部排除，
#     且**每道闸门都能各自独立排除**，不靠串联侥幸。

ZMD_GREEN_G_MIN = 80        # G 通道绝对下限（主色 G=139，给抗锯齿留余量）
ZMD_GREEN_DIFF_MIN = 25     # (g-r) 与 (g-b) 的下限：饱和绿才有；灰白背景≈0
ZMD_COMP_STEP = 4           # 连通域降采样步长：整块按钮 112x40 -> 28x10 格

# 几何闸门。实测按钮 275 格 / 112x40 / 宽高比 2.80 / y0=772（=0.935H）。
ZMD_MIN_CELLS = 90          # 90 格 ≈ 1440 真实像素。胶囊 121 也过这条，
                            # 靠下面的「高 <= 64」与「底部带」两关拒掉。
ZMD_W_MIN, ZMD_W_MAX = 80, 220
ZMD_H_MIN, ZMD_H_MAX = 28, 64
ZMD_WH_MIN, ZMD_WH_MAX = 2.0, 4.0
# 底部带：「开始任务」是内容区底部的主操作按钮。用**比例**不用绝对 y（INV-2/INV-39）。
ZMD_BOTTOM_FRAC = 0.85

# 「盒内有白色文字」：三通道都 >=230（即「开始任务」四字 + 播放三角）。
# 实测按钮 0.149、胶囊 0.243（胶囊也有白字，但它过不了几何闸门），
# 而纯色绿块白占比为 0 ⇒ 这条专门拒绝**无字的绿色色块**（进度条、状态灯、
# 纯色面板、整片绿背景），它们的几何尺寸可能骗过前面的闸门。
ZMD_WHITE_MIN = 230
ZMD_WHITE_FRAC_MIN = 0.02

# 唯一性（INV-24）：第二名**白合格**候选的面积必须 < 最优的 0.5 倍。
# 取 0.5 而不是「差一点」：同款按钮若真有两个（例如确认弹窗），面积必然
# 接近；0.5 允许界面上另有一个明显更小的绿色块而不误杀。
ZMD_UNIQUE_RATIO = 0.5


def zmd_green_mask(frame_rgb):
    """MaaEnd 界面的「饱和绿」掩码，返回 HxW 的 bool ndarray。

    判据（三通道都参与，理由见本段开头的注释）::

        g >= ZMD_GREEN_G_MIN  and  (g-r) >= 25  and  (g-b) >= 25

    ⚠️ 必须先转 **int16 再逐通道相减**：uint8 相减会**回绕**（0-255 变 1），
    把背景 (243,244,244) 也判成绿色 —— 这种错误不报错，只是掩码全错，
    于是后面所有几何判据都在错误数据上算。
    """
    a = np.asarray(frame_rgb, dtype=np.int16)
    r = a[:, :, 0]
    g = a[:, :, 1]
    b = a[:, :, 2]
    return ((g >= ZMD_GREEN_G_MIN)
            & ((g - r) >= ZMD_GREEN_DIFF_MIN)
            & ((g - b) >= ZMD_GREEN_DIFF_MIN))


def zmd_components(mask, step=ZMD_COMP_STEP):
    """把绿色掩码拆成连通域，返回按 `cells` 降序的列表。

    每个元素::

        {"box": (x0, y0, x1, y1),   # 半开区间，**真实像素**
         "center": (cx, cy),        # **真实像素**
         "w": int, "h": int,        # **真实像素**
         "cells": int}              # **降采样格数**，不是像素数！

    ⚠️ **单位不统一是故意的，调用方别直接比**：box/center/w/h 已按 step
    换算回真实像素（给点击用），而 cells 是降采样后的格数；要估真实像素
    面积须 `cells * step * step`。`zmd_locate_start` 返回的
    `area` 就是这个估计值。

    做法：先 `reshape(H//S, S, W//S, S).any(axis=(1, 3))` 做 S 倍降采样
    （任一子格有绿即该格为真），再做纯 Python 4 邻接 BFS。

    为什么降采样：本仓库只有 numpy / Pillow（无 cv2、无 scipy），全分辨率的
    逐像素 BFS 在 1201x826 上仍要访问 ~百万像素；step=4 后只需 300x206 格，
    整帧 90 个连通域毫秒级跑完。代价是**边界精度是 step 的整数倍**（±3px），
    对「点击按钮中心」这个用途无影响。

    为什么形状取 H//S、W//S（**截断**）而不是向上取整：截断保证 reshape
    尺寸严格自洽，不必补边；代价是右/下不足 S 像素的那一条不参与判定
    （1201x826 时丢最后 1 列、2 行）。参考帧上按钮 y1=812、帧高 826，
    余量 14px，故不会被截断吃掉。
    """
    m = np.asarray(mask, dtype=bool)
    if m.ndim != 2:
        raise ValueError(f"zmd_components 需要 HxW 的 bool 掩码，收到 shape={m.shape}")
    step = int(step)
    if step < 1:
        raise ValueError(f"zmd_components 的 step 必须 >= 1，收到 {step}")
    H, W = m.shape
    h2, w2 = H // step, W // step
    if h2 < 1 or w2 < 1:
        return []
    sm = m[: h2 * step, : w2 * step].reshape(h2, step, w2, step).any(axis=(1, 3))

    seen = np.zeros((h2, w2), dtype=bool)
    comps = []
    for sy in range(h2):
        for sx in range(w2):
            if not sm[sy, sx] or seen[sy, sx]:
                continue
            stack = [(sy, sx)]
            seen[sy, sx] = True
            miny = maxy = sy
            minx = maxx = sx
            n = 0
            while stack:
                cy, cx = stack.pop()
                n += 1
                if cy < miny:
                    miny = cy
                elif cy > maxy:
                    maxy = cy
                if cx < minx:
                    minx = cx
                elif cx > maxx:
                    maxx = cx
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h2 and 0 <= nx < w2 and sm[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            x0, y0 = minx * step, miny * step
            x1, y1 = (maxx + 1) * step, (maxy + 1) * step
            comps.append({
                "box": (x0, y0, x1, y1),
                "center": ((x0 + x1) // 2, (y0 + y1) // 2),
                "w": x1 - x0,
                "h": y1 - y0,
                "cells": n,
            })
    comps.sort(key=lambda c: -c["cells"])
    return comps


def zmd_locate_start(frame_rgb, log=None):
    """MaaEnd 定位总入口：在底部找到绿色「▶ 开始任务」按钮。

    返回::

        {"button": {"box": (x0, y0, x1, y1),   # 半开区间，真实像素
                    "center": (cx, cy),        # 真实像素，点击用
                    "area": int},              # 真实像素**估计** = cells*step*step
         "candidates": [{"box":..., "center":..., "area":..., "white_frac":...}, ...],
         "frame_size": (W, H)}

    ⚠️ `area` 的单位是「降采样格数 × step²」的**估计值**，与
    `box` 的真实像素面积同量级但不精确相等（step=4 时逐边最多差 4px）。
    它只用于**比较排序与唯一性判定**，不要拿去当实际像素面积或填充率用。
    `candidates` 只含**过了几何闸门**的块（按 area 降序）；`white_frac`
    低于 `ZMD_WHITE_FRAC_MIN` 的那些就是被白字闸门拒掉的，保留在列表里
    是为了报错时能列出「差在哪」。

    判据（四道闸门，全部成立才算候选）：
      1. 格数 >= ZMD_MIN_CELLS（90 格 ≈ 1440 真实像素）—— 排除勾选圆点(23 格)
      2. 宽 ∈ [80, 220]、高 ∈ [28, 64]、宽高比 ∈ [2.0, 4.0] —— 排除绿色胶囊(84x24)
      3. y0 >= ZMD_BOTTOM_FRAC * H —— 按钮在底部带；排除顶部/侧栏的绿色元素
      4. 盒内白色占比 >= ZMD_WHITE_FRAC_MIN —— 必须有文字；排除纯色绿块
    再在**白合格**候选里取面积最大者，并按 INV-24 做唯一性检查。

    ⚠️ 为什么必须做唯一性检查（INV-24）：只取最大面积是在赌「界面上没有
    第二个同款绿块」。绿色在 MaaEnd 里是**状态色的首选**（勾选、在线、
    进行中），一旦某处出现一个尺寸相近的绿块（例如「运行中」进度条），
    本函数就会**静默点在那个块上** —— 不报错、不崩溃，只是点了别处。
    故第二个白合格候选面积 >= 最优的 ZMD_UNIQUE_RATIO 倍时**拒绝**而非赌。

    ⚠️ 本函数**不做**页面判定（INV-26 / INV-33）：它只回答「这一帧里有没有
    那个绿色按钮、在哪」。要确认「当前在任务页、且允许点击」，须另配页面
    锚点；单凭一个可点元素不能确定页面。
    """
    a = np.asarray(frame_rgb, dtype=np.int16)
    if a.ndim != 3 or a.shape[2] < 3:
        raise GuardFailure(
            "INV-24", f"MaaEnd 定位失败：期望 HxWx3 的 RGB 帧，收到 shape={a.shape}")
    H, W = a.shape[:2]
    mask = zmd_green_mask(a)
    comps = zmd_components(mask)

    if log:
        log(f"    [zmd] 绿像素 {int(mask.sum())}/{mask.size}，连通域 {len(comps)} 个，"
            f"底部带 y >= {int(H * ZMD_BOTTOM_FRAC)}（帧 {W}x{H}）")

    cands, rejected = [], []
    for c in comps:
        x0, y0, x1, y1 = c["box"]
        w, h = c["w"], c["h"]
        area = c["cells"] * ZMD_COMP_STEP * ZMD_COMP_STEP
        reason = None
        if c["cells"] < ZMD_MIN_CELLS:
            reason = f"格数 {c['cells']} < {ZMD_MIN_CELLS}（太小）"
        elif not (ZMD_W_MIN <= w <= ZMD_W_MAX):
            reason = f"宽 {w} 不在 [{ZMD_W_MIN}, {ZMD_W_MAX}]"
        elif not (ZMD_H_MIN <= h <= ZMD_H_MAX):
            reason = f"高 {h} 不在 [{ZMD_H_MIN}, {ZMD_H_MAX}]"
        elif not (ZMD_WH_MIN <= w / float(h) <= ZMD_WH_MAX):
            reason = f"宽高比 {w / float(h):.2f} 不在 [{ZMD_WH_MIN}, {ZMD_WH_MAX}]"
        elif y0 < H * ZMD_BOTTOM_FRAC:
            reason = f"y0={y0} 不在底部带（需 >= {int(H * ZMD_BOTTOM_FRAC)}）"
        if reason is not None:
            rejected.append((c, reason))
            continue

        # 白字占比按**真实像素**的盒面积算（盒坐标已换算回真实像素）
        sub = a[y0:y1, x0:x1]
        n_px = sub.shape[0] * sub.shape[1]
        white = int(((sub[:, :, 0] >= ZMD_WHITE_MIN)
                     & (sub[:, :, 1] >= ZMD_WHITE_MIN)
                     & (sub[:, :, 2] >= ZMD_WHITE_MIN)).sum())
        cands.append({
            "box": c["box"],
            "center": c["center"],
            "area": area,
            "white_frac": (white / n_px) if n_px else 0.0,
        })

    if log:
        for c, reason in rejected:
            log(f"    [zmd] 拒绝 cells={c['cells']:4d} box={c['box']} "
                f"w={c['w']:3d} h={c['h']:3d} —— {reason}")

    if not comps:
        raise GuardFailure(
            "INV-24",
            "MaaEnd 定位失败：全帧一个绿色连通域都没有。\n"
            "  => 可能原因：帧全黑（INV-17 抓帧越界/被遮挡）、不在任务页、"
            "或界面改版（按钮不再是饱和绿）。")
    if not cands:
        raise GuardFailure(
            "INV-24",
            f"MaaEnd 定位失败：{len(comps)} 个绿色连通域没有一个通过几何闸门"
            f"（格数>={ZMD_MIN_CELLS}、宽[{ZMD_W_MIN},{ZMD_W_MAX}]、"
            f"高[{ZMD_H_MIN},{ZMD_H_MAX}]、宽高比[{ZMD_WH_MIN},{ZMD_WH_MAX}]、"
            f"y0>={int(H * ZMD_BOTTOM_FRAC)}）。\n"
            f"  最大的几个：{[c['box'] for c in comps[:5]]}\n"
            "  => 可能原因：按钮被遮挡/被滚动出底部、窗口过矮、任务正在运行"
            "（按钮被禁用变灰）、或界面改版。")

    eligible = [c for c in cands if c["white_frac"] >= ZMD_WHITE_FRAC_MIN]
    if not eligible:
        lines = [f"  box={c['box']} area={c['area']} 白占比={c['white_frac']:.4f}"
                 for c in sorted(cands, key=lambda x: -x["area"])[:6]]
        raise GuardFailure(
            "INV-24",
            f"MaaEnd 定位失败：{len(cands)} 个几何候选里没有一个盒内白占比 "
            f">= {ZMD_WHITE_FRAC_MIN}（无文字 ⇒ 是纯色绿块，不是按钮）。\n"
            + "\n".join(lines))

    eligible.sort(key=lambda c: -c["area"])
    best = eligible[0]
    if len(eligible) >= 2 and eligible[1]["area"] >= best["area"] * ZMD_UNIQUE_RATIO:
        lines = [f"  box={c['box']} area={c['area']} 白占比={c['white_frac']:.4f}"
                 for c in eligible[:6]]
        raise GuardFailure(
            "INV-24",
            f"MaaEnd 定位失败：唯一性不成立 —— 有 {len(eligible)} 个白合格的绿色候选，"
            f"第二名 area={eligible[1]['area']} 不小于最优的 {ZMD_UNIQUE_RATIO:g} 倍"
            f"（最优 {best['area']}）。\n" + "\n".join(lines))

    if log:
        bx0, by0, bx1, by1 = best["box"]
        log(f"    [zmd] 「开始任务」按钮 x={bx0}..{bx1} y={by0}..{by1} "
            f"中心={best['center']} area={best['area']} "
            f"白占比={best['white_frac']:.4f}（候选 {len(eligible)}/{len(cands)} 白合格）")

    return {
        "button": {
            "box": best["box"],
            "center": best["center"],
            "area": best["area"],
        },
        "candidates": sorted(cands, key=lambda c: -c["area"]),
        "frame_size": (W, H),
    }


# ==========================================================================
# 2) 运行判据：mxu-tauri.log + 时间戳基线闸（原 verdict.py 尾部）
# ==========================================================================

# ============================================================================
# MaaEnd（program key = "zmd"）运行判据
#
# 与 ok-nte 的差别（实测 2026-10-16 ~ 10-18，E:/TOOLS/ScriptsGames/zmd/debug）：
#
#   · MaaEnd 把「本次任务提交」与「agent 收尾」写进 **Rust 后端** 的
#     mxu-tauri.log；同目录另两个文件（<date>-<n>.log 应用日志、
#     maafw.log MaaFramework 日志）**每次启动都被清空重建**，
#     故判据**只认** mxu-tauri.log。这不是猜的：应用日志自己写着
#         [App] Auto-cleared log files and debug artifacts on launch: 2
#         [App] Restored runtime logs: skipped (auto-clear on launch enabled)
#
#   · 行格式 [2026-10-17][23:43:58][INFO][mxu_lib::...] 消息
#     ⇒ **每一行都自带时间戳**，这是本判据能加「时间戳第二道闸」的前提
#     （见 ZmdLogWindow 的 docstring）。
#
#   · 一次完整运行（实测 4 次：10-16 22:24、10-17 23:07 / 23:19 / 23:43）
#     在日志里的形态：
#         [start_tasks] All tasks submitted, total: 12 task_ids
#         ...（业务过程）
#         [MXU_KILLPROC] Killing process: Endfield.exe
#         [MXU_KILLPROC] taskkill succeeded: ...Endfield.exe...
#         stop_agent_impl called for instance: yj2gs5w
#         [stop_agent] Stopping 2 agent client(s) and 2 child process(es)...
#         Background: Agent #0 child process exited
# ============================================================================

from datetime import datetime  # 追加段新增：按行时间戳过滤（上方代码零改动）

ZMD_LOGDIR = Path("E:/TOOLS/ScriptsGames/zmd/debug")
ZMD_LOG_NAME = "mxu-tauri.log"

# ★ 开始标记：任务**已提交**（实测 4 次都出现在运行起点）
ZMD_START_MARK = r"\[start_tasks\] All tasks submitted, total:\s*\d+\s+task_ids"

# ★★ 终止标记：agent 收尾，**本次实现里唯一的完成信号**
# 实测同一次收尾会重复调用 1~3 次（10-17 23:17 那次连写 3 条），
# 故证据只取前 2 条，**不当成计数**用。
ZMD_STOP_MARK = r"stop_agent_impl called for instance:\s*\S+"

# 终止标记的**旁证**：收尾进程的动作。它出现在 stop_agent_impl 之后，
# 不能单独当完成信号（它属于「正在收尾」，收尾仍可能失败）。
ZMD_STOP_SOFT = r"\[stop_agent\] Stopping\s+\d+\s+agent client\(s\)"

# ★ 启动失败：任务**从未提交**（实测 5 次，全部落在「上次 stop 之后、本次 start 之前」）
ZMD_PRETASK_FAIL = r"run_pretask finished with exit code:\s*1\b"

# 关游戏（可选证据，取决于任务配置是否勾了「结束后关闭游戏」）
ZMD_KILL_GAME = (
    r"\[MXU_KILLPROC\]\s*(?:Killing process|taskkill succeeded)[^\n]*Endfield\.exe")

# agent 侧报错原文（go-service stdout 转写）。
# ⚠️ 行里带 ANSI 颜色码（ESC[31mERR ESC[0m），故只匹配 ERR 字面，
# 不依赖颜色码的位置；error= 是 Go 侧结构化字段。
ZMD_AGENT_ERR = r"\[agent\][^\n]*\[(?:stdout|stderr)\][^\n]*(?:ERR|error=|无法找到)"

# 自检只看日志尾部：mxu-tauri.log 跨启动追加（3 天 476KB），长期跑会到几十 MB
ZMD_SELFCHECK_BYTES = 8 << 20

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_ZMD_TS_RE = re.compile(
    r"^\[(\d{4})-(\d{2})-(\d{2})\]\[(\d{2}):(\d{2}):(\d{2})\]")

_ZMD_STOP_MARK_RX = re.compile(ZMD_STOP_MARK)
_ZMD_START_MARK_RX = re.compile(ZMD_START_MARK)


def zmd_parse_ts(line):
    """取一行日志开头的 [日期][时间]；没有则 None。

    为什么要它：MaaEnd 启动会清理日志（见段首），清理/重写之后
    **字节偏移与内容不再对应**，此时判断「这行是不是本次运行的」
    唯一可靠依据就是行时间戳（每一行都有）。
    解析失败一律返回 None（时间格式一旦被升级改掉，过滤会退回
    「不过滤」，判据方向仍是 RUNNING/待定 —— 由 zmd_log_self_check 兜住）。
    """
    if not line:
        return None
    m = _ZMD_TS_RE.match(line.lstrip("\ufeff").lstrip())
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:      # 例如 [2026-13-45][25:99:99]
        return None


def _zmd_clean(line):
    """证据整形：去 ANSI 颜色码、压缩空白（**保留原文语义**，只去噪声）。"""
    s = _ANSI_RE.sub("", line)
    return re.sub(r"\s+", " ", s).strip()


def _zmd_hits(text, pattern):
    """返回**整行**命中的原文列表（不是匹配片段 —— 证据要看整行上下文）。"""
    rx = re.compile(pattern)
    return [ln for ln in text.splitlines() if rx.search(ln)]


def _zmd_ev(label, lines, limit=2):
    """证据条目：[标签] 原文，每类最多 limit 条。"""
    out = []
    for ln in lines[:limit]:
        s = _zmd_clean(ln)
        if len(s) > 180:
            s = s[:180] + "…"
        out.append(f"[{label}] {s}")
    return out


def zmd_verdict(text, still_running=False):
    """MaaEnd 单次运行的终态判据（只认 mxu-tauri.log 的**本次新增**内容）。

    ## 为什么「有 stop_agent_impl 就是完成」

    MaaEnd 收尾时会把 agent 实例停掉并**写进日志**：
        stop_agent_impl called for instance: yj2gs5w
    实测 4 次完整运行**全部**以它收尾，且它之后紧跟着
    [stop_agent] Stopping N agent client(s)... 与
    Background: Agent #N child process exited。它是本程序里
    **唯一的进程级完成证据** —— 平台界面回到空闲态**不能**单独当证据
    （INV-30：ok-nte 上就是这样把「失败回落」误判成「完成」的）。

    ## 为什么要结合 pretask 失败

    启动失败**根本不产生** stop_agent_impl（任务没提交）。实测失败形态：
        run_pretask finished with exit code: 1
        [agent] [pretask:go-service][stdout] ... launchgamepc.go:158 > 无法找到启动器…
    故判据是「有 pretask 失败 **且** 整个窗口里没有 start_tasks ⇒ FAILED」。
    反过来，窗口里若**先**有 start_tasks（任务已提交）之后又冒 pretask 失败，
    那属于**下一次**运行的尝试，本次仍按 stop 判 SUCCESS ——
    实测 10-17 23:39 / 23:42 两次启动失败都落在第 4 次运行的 start 之前，
    正是这个次序。

    ## ⚠️ 空文本判 UNKNOWN（**与** nte_verdict 的 RUNNING 不同，故意的）

    mxu-tauri.log 是**跨启动追加**的（当前 476KB 里装着 4 次运行的全部内容），
    所以「窗口里一行新增都没有」在 MaaEnd 侧更可能是**路径 / 权限 / mark 时机**
    出了问题，而不是「任务还在跑」。报 RUNNING 会让这类静默失效一路等到超时，
    把「判据坏了」伪装成「任务慢」（INV-30：证据不足须报未知/失败）。

    参数 still_running 与 nte/ww 判据保持同构（调用方不必分支），
    只用于证据文案；**它不改变判定** —— 「进程还在」不是完成证据。
    """
    if not text or not text.strip():
        return UNKNOWN, [
            "读不到日志：本次窗口内 mxu-tauri.log 没有新增行。"
            "（从未跑过任务时属正常；否则先查路径/权限/mark 时机 —— "
            "zmd_log_self_check 列出问题时，判据本身也读不到东西）"]

    starts = _zmd_hits(text, ZMD_START_MARK)
    stops = _zmd_hits(text, ZMD_STOP_MARK)
    softs = _zmd_hits(text, ZMD_STOP_SOFT)
    fails = _zmd_hits(text, ZMD_PRETASK_FAIL)
    kills = _zmd_hits(text, ZMD_KILL_GAME)
    aerrs = _zmd_hits(text, ZMD_AGENT_ERR)

    # --- 1) 有终止标记 ---------------------------------------------------
    if stops:
        ev = _zmd_ev("stop", stops)
        if starts:
            ev += _zmd_ev("start", starts)
        if kills:
            ev += _zmd_ev("killproc", kills)
        if softs:
            ev += _zmd_ev("stop_agent", softs, limit=1)

        if fails and not starts:
            ev = _zmd_ev("pretask_fail", fails) + ev
            ev += _zmd_ev("agent", aerrs)
            return FAILED, [
                f"有终止行，但窗口内没有 start_tasks 且有 {len(fails)} 条 "
                f"pretask 失败 ⇒ 任务从未提交（不是「跑完了」）"] + ev

        why = f"终止标记 {len(stops)} 条（stop_agent_impl）"
        if softs:
            why += f"，收尾动作 {len(softs)} 条"
        if kills:
            why += "，且已确认杀掉 Endfield.exe"
        return SUCCESS, [why + " —— 本次运行已收尾"] + ev

    # --- 2) 无终止标记，但明显是启动失败 --------------------------------
    if fails and not starts:
        ev = _zmd_ev("pretask_fail", fails) + _zmd_ev("agent", aerrs)
        return FAILED, [
            f"启动失败：{len(fails)} 条 run_pretask finished with exit code: 1，"
            f"且窗口内没有 start_tasks ⇒ 任务从未提交"] + ev

    # --- 3) 其余：进行中 -------------------------------------------------
    ev = _zmd_ev("start", starts)
    if fails:
        ev += _zmd_ev("pretask_fail", fails)
    why = "尚无终止信号（未见 stop_agent_impl），任务进行中"
    why += ("（进程仍在运行）" if still_running
            else "（进程已不在，但日志里没有终止行 ⇒ 交给超时兜底）")
    if starts:
        why += f"；已见 {len(starts)} 条 start_tasks"
    return RUNNING, [why] + ev


def zmd_filter_since(text, baseline):
    """丢弃时间戳早于 baseline 的行；baseline 为 None 时原样返回。

    这是「时间戳第二道闸」的**可单测内核**（probe 里直接调它）。
    · 没有时间戳的行（agent stdout 的续行、被截断的半行）**沿用上一行**的
      时间戳 —— 它们是上一行的延续，不能因为「格式不完整」就被无条件放行。
    · 首个时间戳出现之前的行做不了判断，**放行**（保守方向：多读几行历史
      不会假成功 —— 假成功只可能来自「多读进一条 stop」，而任何 stop 行
      都自带时间戳，会被正常过滤）。
    """
    if not text:
        return ""
    if baseline is None:
        return text
    kept = []
    last = None
    for line in text.splitlines():
        ts = zmd_parse_ts(line)
        if ts is not None:
            last = ts
        eff = ts if ts is not None else last
        if eff is not None and eff < baseline:
            continue
        kept.append(line)
    return "\n".join(kept)


def _zmd_read_tail(path, nbytes):
    """读文件尾部 nbytes 字节（UTF-8 容错解码）；读不到返回 None。

    不整文件读：mxu-tauri.log 会一直长（实测 3 天 476KB），
    「取最后一行时间戳」每轮都做，整文件读迟早会把启动拖慢。
    """
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            f.seek(max(0, size - nbytes))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def _zmd_last_ts(path):
    """文件**最后一行**的时间戳 = 本次运行的起始时间基线。

    尾部扫不到时间戳时退化为整文件扫（超长续行占满尾部的极端情形）；
    仍扫不到返回 None ⇒ 不做时间过滤（**降级**，由 zmd_log_self_check 警示，
    别让它静默变成「过滤失效」）。
    """
    for nbytes in (1 << 16, 1 << 26):
        text = _zmd_read_tail(path, nbytes)
        if text is None:
            return None
        for line in reversed(text.splitlines()):
            ts = zmd_parse_ts(line)
            if ts is not None:
                return ts
    return None


def _zmd_log_path():
    """默认日志文件：programs 里 zmd 的 logdir（Program 可覆盖）+ mxu-tauri.log。

    ⚠️ 文件名**不**用 program.log_glob 做通配：MaaEnd 的 debug 目录里还有
    <date>-<n>.log 与 maafw.log，而它们**每次启动都被清空** ——
    通配进来就会把「日志被清」当成「本次没有日志」（静默失效）。
    """
    from ... import programs as programs_mod

    try:
        prog = programs_mod.get("zmd")
    except (KeyError, ValueError):
        prog = None
    logdir = getattr(prog, "logdir", None) or ZMD_LOGDIR
    return Path(logdir) / ZMD_LOG_NAME


class ZmdLogWindow:
    """用**字节偏移 + 行时间戳基线**界定「本次运行」的 MaaEnd 日志窗口。

    ## 为什么字节偏移**不够**（这类假成功只有 INV-30 拦得住）

    LogWindow 的前提是「文件只追加」。MaaEnd **不保证**这一点：
    它启动时会清理日志（应用日志原文 Auto-cleared log files and debug
    artifacts on launch: 2；debug 目录下 <date>-<n>.log 与 maafw.log
    实测每次启动都被清空重建）。只要清理/重写发生在 mark() 之后，
    字节偏移就与内容**错位**：
      · 文件变小 ⇒ 整段重读 ⇒ 读进来的是**清理前的旧内容**；
      · 从旧偏移接着读 ⇒ 从新内容的**中间**切入，看不到本次 start_tasks。
    而 stop_agent_impl 是**唯一**可用的完成信号，上一次运行的它
    就躺在同一个文件里 ⇒ **上一次 run 的 stop_agent 被当成本次的
    完成信号** ⇒ **假成功**。这正是 INV-30 禁止的「证据不足却报成功」。

    ## 所以加第二道闸：按行时间戳过滤

    mxu-tauri.log 每行都以 [日期][时间] 开头。mark() 记下
    **文件最后一行的时间戳**作基线，poll() 丢弃早于基线的行。
    这样即使文件被清空重写 / 被别的实例写入历史 / 整段重读，读进缓冲的
    也**只能是基线之后**的标记 —— 与程序的清理策略**解耦**。
    （实测当前版本 mxu-tauri.log 恰好是跨启动追加的：10-16~10-18 四次运行
    都在同一文件里。但那只是**当前版本的行为**，不是接口承诺 ——
    FAULT #18 的教训正是「程序升级会静默改掉你依赖的细节」。）

    ## 用法

        w = ZmdLogWindow()    # 构造即 mark()：必须在**点开始之前**建
        ...                  # 跑任务（期间反复 poll()）
        v, ev = w.verdict()  # 只看本次新增、且不早于基线的行
    """

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else _zmd_log_path()
        self._seen = None
        self._baseline = None
        self._buf = []
        self.mark()

    def mark(self):
        """记下「本次运行」的起点：字节偏移 + 最后一行时间戳。

        ⚠️ 同时**清空**已累积文本（一个窗口只服务一次运行）。
        LogWindow.mark 只挪偏移、不清缓冲；对 MaaEnd 留着旧文本，
        正好会把上一次的 stop_agent 混进本次证据 —— 那正是本类要防的事。
        """
        self._buf = []
        self._baseline = _zmd_last_ts(self.path)
        try:
            self._seen = self.path.stat().st_size
        except OSError:
            self._seen = None      # 文件还不存在：首次 poll 整段读入

    def _read_from(self, offset):
        """从字节偏移处读到尾（二进制读 + 容错解码）。

        不用文本模式 seek：多字节字符被切在中间时会解码出错/悄悄错位。
        """
        try:
            with self.path.open("rb") as f:
                f.seek(offset)
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _starts_before_baseline(self, raw):
        """从旧偏移读到的新增段，首个时间戳是否早于基线（⇒ 偏移已错位）。

        错位的典型来源：文件被清空后**又长回**到旧偏移以上，此时从旧偏移
        切入的是新文件的**中间**，会漏掉本次 start_tasks。
        时钟回拨也会命中这里 ⇒ 退化为「整段重读 + 时间戳过滤」，
        结果仍是本次内容，方向安全（宁可多读，不可假成功）。
        """
        if self._baseline is None:
            return False
        for line in raw.splitlines():
            ts = zmd_parse_ts(line)
            if ts is not None:
                return ts < self._baseline
        return False

    def poll(self):
        """读本次运行**新增且不早于基线**的行，返回本次新增文本（无则 ""）。

        四种情形：
          · 文件还没出现 / **变小**（被清空、重写）⇒ **整段读**，再按时间戳过滤
          · 文件**变大** ⇒ 从旧偏移读；若首个时间戳早于基线 ⇒ 判为错位，
            改整段读（否则会从新内容的中间切入，丢掉本次 start_tasks）
          · 文件**不变** ⇒ ""
          · 文件读不到 ⇒ ""（当「没有新增」，由 verdict 报 UNKNOWN，
            绝不因为读不到就报成功）

        ⚠️ 整段读时**缓冲区重建**，不是追加：否则同一段内容会被追加两次
        （证据条数虚增，stop 被算成 2 条）。因此返回值在整段读时是
        「按基线过滤后的整文件内容」，**可能与之前返回过的内容重复** ——
        需要累计文本请用 text()（它永远等于「本次运行至今」的那一份）。
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return ""
        prev = self._seen
        whole = False
        if prev is None or size < prev:
            raw, whole = self._read_from(0), True
        elif size > prev:
            raw = self._read_from(prev)
            if self._starts_before_baseline(raw):
                raw, whole = self._read_from(0), True
        else:
            return ""
        self._seen = size
        chunk = zmd_filter_since(raw, self._baseline)
        if whole:
            self._buf = [chunk] if chunk.strip() else []
        elif chunk.strip():
            self._buf.append(chunk)
        return chunk if chunk.strip() else ""

    def text(self):
        """**本次运行**累积的新增日志（已过时间戳闸，不含上一次运行）。"""
        return "\n".join(self._buf)

    def verdict(self, still_running=True):
        """按本次窗口内的文本下判据（默认假设任务还在跑）。"""
        return zmd_verdict(self.text(), still_running=still_running)


def zmd_log_self_check(path=None):
    """校验 MaaEnd 日志**读得到**且**措辞还认得出来**；空列表 = 正常。

    三类问题各返回一条：
      · 文件不存在（「从未跑过任务时属正常」）
      · 文件读不到（权限 / 被独占占用）
      · 历史里认不出 start / stop 标记（**最危险**：MaaEnd 升级改了措辞，
        判据会永远 RUNNING，静默失效 —— FAULT #18 同型）
    """
    problems = []
    p = Path(path) if path is not None else _zmd_log_path()

    if not p.exists():
        problems.append(
            f"MaaEnd: 日志文件不存在 {p}"
            f"（从未跑过任务时属正常；跑过一次再来查）")
        return problems

    text = _zmd_read_tail(p, ZMD_SELFCHECK_BYTES)
    if text is None:
        problems.append(f"MaaEnd: 日志文件读不到 {p}（权限 / 被独占占用？）")
        return problems

    if not _ZMD_STOP_MARK_RX.search(text):
        problems.append(
            f"MaaEnd: 历史日志里认不出终止标记 {ZMD_STOP_MARK!r}"
            f"（从未跑过任务时属正常；跑过仍认不出 ⇒ MaaEnd 升级改了措辞，"
            f"判据会永远 RUNNING —— FAULT #18 同型，须重新实测）({p})")
    if not _ZMD_START_MARK_RX.search(text):
        problems.append(
            f"MaaEnd: 历史日志里认不出开始标记 {ZMD_START_MARK!r}"
            f"（从未跑过任务时属正常；否则「启动失败」判据会退化）({p})")
    return problems



# ==========================================================================
# 节点 8 的 MaaEnd 实现（8b~8e）—— 原 orchestrator/steps/step8_run_task.py 的 zmd 段，
# docs/adr/0003 阶段二搬迁
# ==========================================================================
#
# 调用入口：apps.get("zmd").zmd_run(state, args, frame, log)
# apps/zmd/nodes/step8_run_task.py 的 body() 只做一行分派，不认识这段的任何细节。
#
# ⚠️ 为什么 8e 阶段**不抓帧**：点下「开始任务」后 pretask 会把启动器与游戏拉起来，
# 游戏**全屏**盖在 MaaEnd 之上 ⇒ 对 MaaEnd 的 rect 抓帧得到的是**游戏的像素**。
# 尺寸校验（INV-1）仍然通过、内容也不黑（更不是纯色），**没有任何不变量会报警**，
# 只是分析错画面 —— HANDOFF §2.1 那类静默失效。故 8e 一律只读日志；
# 点前那次抓帧（用来定位按钮）仍然是必须的。

ZMD_START_CONFIRM_SECONDS = 45.0   # 点击后等「任务已接单」日志的上限
ZMD_SETTLE_SECONDS = 20.0          # 见到终止标记后的收尾宽限（同 NTE_SETTLE_SECONDS）
ZMD_CLICK_RETRIES = 2
ZMD_POLL_SECONDS = 2.0             # 日志轮询间隔（比画面轮询慢：没必要 0.2s 读盘）


def zmd_locate(state, frame, log):
    """8b：在底部控制条里定位绿色「开始任务」。返回 (button, screen_xy)。"""
    log("\n[8b] 定位「开始任务」按钮（MaaEnd 单页，无导航步骤）")
    info = zmd_locate_start(frame.rgb, log=log)
    btn = info["button"]
    log(f"  按钮 box={tuple(btn['box'])} center={tuple(btn['center'])} "
        f"面积={btn['area']}px 候选={len(info['candidates'])} 个")
    sx, sy = frame.screen_xy(*btn["center"])
    log(f"  屏幕坐标 ({sx},{sy})  帧原点=({frame.left},{frame.top})")
    return btn, (sx, sy)


def zmd_click_and_confirm(state, frame, log, zw, prog):
    """8c + 8d：点击「开始任务」，并确认**框架真的接单了**。

    确认分三级证据（弱 -> 强），只有弱证据时明确记缺：
      (a) 日志出现 [start_tasks] All tasks submitted, total: N task_ids
          —— 最强：MaaEnd 后端已把任务交给 MaaFramework。
      (b) 日志出现 run_pretask finished with exit code: 1
          —— 明确的**失败**（实测：启动器路径没填时就是这样）。
      (c) 画面变化（按钮形态变了）—— 弱证据，可能只是弹了个窗。

    返回 ("started"|"started_unconfirmed_log"|"pretask_failed"|"no_effect", detail)。
    """
    from ...orchestrator import CLICK_RETRY_INTERVAL
    from ...steps import context   # 函数内 import：避免 apps <-> steps 的导入环

    for attempt in range(1, ZMD_CLICK_RETRIES + 1):
        hwnd = context.require_hwnd(state, log=None)
        sx, sy = frame.screen_xy(*zmd_locate(state, frame, log)[0]["center"])
        state.set("hwnd", hwnd)          # INV-14：每轮重新发现，绝不缓存
        log(f"\n[8c] 点击「开始任务」({sx},{sy})  第 {attempt}/{ZMD_CLICK_RETRIES} 次")
        try:
            input_mod.guarded_click(hwnd, sx, sy, log=log)
        except GuardFailure as e:
            log(f"  [!!] [{e.invariant}] {e.detail.splitlines()[0]}")
            if attempt == ZMD_CLICK_RETRIES:
                raise
            time.sleep(CLICK_RETRY_INTERVAL)
            continue

        log(f"\n[8d] 确认点击生效：等日志（≤{ZMD_START_CONFIRM_SECONDS:.0f}s）")
        t0 = time.time()
        while time.time() - t0 < ZMD_START_CONFIRM_SECONDS:
            zw.poll()
            txt = zw.text()
            m = re.search(ZMD_START_MARK, txt)
            if m:
                log(f"  [OK] 任务已接单：{m.group(0).strip()}")
                return "started", m.group(0).strip()
            if re.search(ZMD_PRETASK_FAIL, txt):
                log("  [!!] 日志出现 run_pretask 非零退出 —— 前置任务失败")
                return "pretask_failed", "run_pretask finished with exit code: 1"
            time.sleep(ZMD_POLL_SECONDS)

        # 弱证据：画面是否变了（重新抓帧比对；注意此刻可能已被游戏遮挡）
        # ⚠️ frame_changed 返回 **tuple**（changed, why）。原实现写的是
        #    `changed = frame_changed(...)` 后判 `changed is True` —— 恒为 False，
        #    弱证据分支从来没生效过（静默）。现按返回值解包。
        try:
            hwnd2 = context.require_hwnd(state, log=None)
            f2 = capture_mod.grab_frame(hwnd2, strict_content=False)
            # frame_changed 吃的是 **RGB ndarray**（frame.rgb），不是 Frame 对象 ——
            # 原实现传的是 Frame，一旦走到这里会 AttributeError（和 is True 那个 bug
            # 同一个分支，因为日志永远先成功所以从未暴露）。
            changed, _why = frame_changed(frame.rgb, f2.rgb, log=None)
        except GuardFailure as e:
            log(f"  [注] 复抓帧失败（{e.invariant}）：无法用画面佐证")
            changed = None
        if changed is True:
            log("  [警告] 没有拿到日志证据，但画面变了 —— 继续等待（记为弱证据）")
            return "started_unconfirmed_log", "仅有画面变化"
        log("  [!!] 点击后日志与画面都没有变化")
        if attempt == ZMD_CLICK_RETRIES:
            return "no_effect", "点击后画面与日志均无变化"
        time.sleep(CLICK_RETRY_INTERVAL)
    return "no_effect", "重试耗尽"


def zmd_wait_completion(state, args, log, zw, prog):
    """8e：等 MaaEnd 自己跑完。返回 (result, detail, shot_path=None)。

    判据（全部来自 mxu-tauri.log，**不抓帧**）：
      主 : stop_agent_impl called for instance: ...  —— 唯一明确的终止信号
      辅 : [MXU_KILLPROC] Killing process: ...      —— 任务链走到最后一项（关游戏）
           实测该内置任务排在 12 个 entry 的最后，故可作为完成证据，但**需注明**
      失败: run_pretask finished with exit code: 非零
    证据不足（MaaEnd 进程消失却无终止信号）⇒ UNKNOWN（INV-30），绝不默认成功。
    """
    log(f"\n[8e] 等待完成（MaaEnd 日志判据，只读 mxu-tauri.log）："
        f"采样 {ZMD_POLL_SECONDS:.0f}s；兜底 {args.total_timeout:.0f}s")
    log(f"  日志：{getattr(zw, 'path', '?')}")
    started = time.time()
    last_v = None
    last_report = 0.0
    while True:
        now = time.time()
        elapsed = now - started
        if elapsed > args.total_timeout:
            return TIMEOUT, f"超过兜底上限 {args.total_timeout:.0f}s 仍无终止信号", None

        zw.poll()
        alive = bool(window.running(prog))
        v, ev = zw.verdict(still_running=alive)
        if v != last_v:
            tail = ev[-1][:120] if ev else ""
            log(f"  +{elapsed:6.0f}s  日志判据：{v}  {tail}")
            last_v = v

        if v == SUCCESS:
            log(f"  +{elapsed:6.0f}s  *** 完成 ***（日志终止标记）")
            for e in ev:
                log(f"        {e[:160]}")
            # 收尾宽限（与 ok-nte 同策略，FAULT #27）：终止信号是「即将退出」的
            # 宣告，随后才关游戏/退子进程。抢在这中间动手会打断它。
            end = time.time() + ZMD_SETTLE_SECONDS
            while time.time() < end:
                zw.poll()
                if not window.running(prog):
                    break
                time.sleep(ZMD_POLL_SECONDS)
            return COMPLETED, "日志终止信号：" + "；".join(ev[-2:]), None

        if v == FAILED:
            return FAILED, "日志显示失败：" + "；".join(ev[-2:]), None

        # 辅助证据：任务链已走到最后一项（关游戏）。它排在 12 个 entry 的最后，
        # 故「它开始执行」确实能证明前面 11 项已跑完；但 MaaEnd 紧接着还会打
        # stop_agent_impl（实测 2026-10-18 22:26:36 taskkill succeeded → 22:26:37
        # stop_agent_impl，只差 1s）。所以这里**不**立刻收工，而是在收尾宽限里
        # 继续 poll：拿到主判据就用主判据。否则 detail 会永久写着「无 stop_agent
        # 标记」，让事后读 state.json 的人以为那个信号从未出现（证据记录失真）。
        txt = zw.text()
        mk = re.search(ZMD_KILL_GAME, txt)
        if mk:
            log(f"  +{elapsed:6.0f}s  日志出现关游戏记录：{mk.group(0).strip()}")
            end = time.time() + ZMD_SETTLE_SECONDS
            while time.time() < end:
                zw.poll()
                v2, ev2 = zw.verdict(still_running=True)
                if v2 == SUCCESS:
                    log(f"  +{time.time()-started:6.0f}s  *** 完成 ***"
                        "（关游戏后拿到日志终止标记）")
                    for e in ev2:
                        log(f"        {e[:160]}")
                    return COMPLETED, "日志终止信号：" + "；".join(ev2[-2:]), None
                if not window.running(prog):
                    break
                time.sleep(ZMD_POLL_SECONDS)
            return (COMPLETED,
                    "任务链走到「关游戏」内置任务，宽限期内未看到 stop_agent 标记："
                    + mk.group(0).strip(), None)

        if not alive:
            return UNKNOWN, (
                "MaaEnd 进程消失，但日志里没有终止信号 —— 无法区分"
                "「跑完了自己退出」与「崩溃/被外部关闭」。证据不足，不默认成功"
                "（INV-30）。"), None

        if now - last_report > 60:
            last_report = now
            log(f"  +{elapsed:6.0f}s  … 仍在运行（日志 {len(txt)} 字符）")
        time.sleep(ZMD_POLL_SECONDS)


def zmd_run(state, args, frame, log):
    """zmd 的 8b~8e 全流程，返回节点 8 的**最终** (status, data, note)。

    两条早退路径（--only-locate / --dry-run）直接给 status；
    真正要等待的那条路径交给 finish() 统一做 result -> status 映射 ——
    映射只有一处（frameops.finish），主流程与 zmd 共用，日后不会各自漂移。
    （第一版这里返回 (result, detail, frame_path) 而早退分支返回
    (status, data, note)，两种形状混在一处，于是 --only-locate 明明定位成功
    却被 finish() 当成未知 result 映射成 failed、退出码 1。已改正。）
    """
    prog = programs_mod.get("zmd")
    btn, sp = zmd_locate(state, frame, log)
    shot(state, frame, "zmd-located", log)

    if args.only_locate:
        return ("ok",
                {"mode": "only-locate", "program": prog.key,
                 "screen_coords": list(sp),
                 "button_box": list(btn["box"]),
                 "button_center": list(btn["center"]),
                 "offline": bool(args.adopt_frame)},
                f"定位成功（MaaEnd）按钮窗口内 {tuple(btn['center'])}")

    if args.dry_run:
        log("\n[DRY RUN] MaaEnd：定位通过，未点击")
        # 与主流程的 dry-run 分支保持一致：把 result 写成 completed。
        # 不写的话节点 9 读到 result=None 会走「清理路径」，而 dry-run 又不许杀，
        # 于是报一个「仍有进程存活」的假失败（实测整条链就是这样停在最后一节）。
        state.set("result", COMPLETED)
        return ("ok", {"mode": "dry-run", "program": prog.key, "result": COMPLETED,
                       "screen_coords": list(sp)}, "dry-run 定位通过")

    # ★ 日志窗口必须在点击**之前**武装（FAULT #25 的同一个道理）：
    # 基线若取在点击之后，点击到构造之间写的日志全丢 ⇒ 永远等不到完成。
    zw = ZmdLogWindow()
    log(f"\n[8e-预备] 已武装 MaaEnd 日志窗口（点击前）：{getattr(zw, 'path', '?')}")

    verdict_kind, detail = zmd_click_and_confirm(state, frame, log, zw, prog)
    if verdict_kind == "pretask_failed":
        return finish(state, FAILED, f"前置任务失败：{detail}", None, log)
    if verdict_kind == "no_effect":
        raise GuardFailure("INV-8", f"点击「开始任务」{ZMD_CLICK_RETRIES} 次无效：{detail}")
    if verdict_kind == "started_unconfirmed_log":
        log("  [注] 继续按日志等待完成，但本次运行**缺少「任务已接单」证据**")

    result, why, path = zmd_wait_completion(state, args, log, zw, prog)
    return finish(state, result, why, path, log)

# ==========================================================================
# 3) 自我更新闸门（节点 5 等它更完 / 节点 6 点「知道了」）
# ==========================================================================
#
# ## 实测（2026-10-19 23:35~23:43，v2.34.0-rc.1 -> v2.34.0，更新包 300MB）
#
# MaaEnd 自带应用本体更新（右上角铃铛 -> 下载 -> 解压替换 -> **自动重启** ->
# 模态框「更新完成 / 已成功更新到最新版本」+ 右下绿色「知道了」）。全生命周期
# 都在 `debug/mxu-tauri*.log`（模块 `mxu_lib::commands::download` /
# `::update`）与 `debug/<date>-<n>.log`（应用日志）里留下了**可判读的标记**：
#
#   1. `[INFO][mxu_lib::commands::download] 找到匹配的 Release: v2.34.0`
#   2. `download_file: https://.../MaaEnd-win-x86_64-v2.34.0.zip -> ...cache/...`
#      +`download_file session_id: 1`（约 7 分钟，300MB）
#   3. `download_file completed: 313755110 bytes -> ...MaaEnd-win-x86_64-v2.34.0.zip`
#   4. `[mxu_lib::commands::update] extract_zip called ...` -> `extract_zip success`
#      -> `apply_full_update called` -> 大量 `Moved to old: ...cache/old/...`
#   5. 重启（旧 mxu-tauri.log 被轮转成 mxu-tauri_<date>_<HH-MM-SS>.log），
#      新应用日志里出现 `[App] 检测到刚更新完成: v2.34.0`（= 弹窗那一刻）
#
# ## 为什么必须挡在节点 5（而不是只在节点 6 点按钮）
#
# 解压替换发生在应用**运行期间**，随后进程自己重启 —— 若正好落在节点 5
# 的采样窗口里，节点 5 会诚实但无用地说「窗口未就绪」；而节点 6 的身份校验
# 也会因为「绿按钮被模态遮罩压暗」（实测白占比 0.171 -> 0.000）而失败。
# 所以两段闸门各管一段：
#
#   节点 5 `zmd_update_wait`    只读日志，等「下载/安装/重启」收敛，**不点**
#                               （此时可能还没有可用帧）；先它、后 require_hwnd，
#                               因为重启会换 hwnd（INV-14）。
#   节点 6 `zmd_update_dismiss` 已经能抓帧 + 置前台，按**双证据**点「知道了」：
#                               应用日志有 `检测到刚更新完成` **且** 帧里有
#                               ack 形态绿块。只有日志没有按钮 ⇒ 立即判「弹窗
#                               已不在」返回（标记会一直留在日志里，不能空等）；
#                               只有按钮没有日志 ⇒ **不点**（避免点到同款绿块）。
#
# ⚠️ 更新包只认文件名里的 `MaaEnd-win-x86_64`：MaaEnd 还会下**资源包 /
#    MaaFramework 包**（别的文件名），把那些当自我更新就会白等半小时。
#
# ⚠️ 应用日志 `<date>-<n>.log` 每次启动都被清空重建（`Auto-cleared log files
#    and debug artifacts on launch: 2`），所以「最新一份」天然属于**当前实例**；
#    绝不要用通配把 maafw.log 之类一起读进来。

ZMD_APP_LOG_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d+)\.log$")
ZMD_UPD_ZIP_MARK = "MaaEnd-win-x86_64"
ZMD_UPD_DETECT = r"找到匹配的 Release:"
ZMD_UPD_DL_START = r"download_file:"
ZMD_UPD_DL_DONE = r"download_file completed:"
ZMD_UPD_INSTALL = r"\[mxu_lib::commands::update\]"
ZMD_UPD_FINISHED = r"检测到刚更新完成"

ZMD_UPDATE_WAIT_SECONDS = 1800.0     # 实测 300MB 约 7 分钟；给到 30 分钟
ZMD_UPDATE_POLL = 3.0                # 日志轮询间隔（下载期间没必要更密）
ZMD_UPDATE_LOOKBACK = 3600.0         # 只看最近 1 小时的行（排除前一天的旧安装）
ZMD_UPDATE_DETECT_GRACE = 90.0       # 只有「找到匹配的 Release」时的等待宽限

# 「知道了」的几何判据（与 zmd_locate_start 的**四道闸门不同**，见 fixture 实测：
# done 帧 76x40 cells=181 白占比 0.171 中心 (834,704)；被遮罩压暗的「开始任务」
# 104x28 cells=132 白占比 0.000；下载中帧是正常的 116x36 白占比 0.087）
ZMD_ACK_MIN_CELLS = 60
ZMD_ACK_W_MIN, ZMD_ACK_W_MAX = 50, 160
ZMD_ACK_H_MIN, ZMD_ACK_H_MAX = 24, 64
ZMD_ACK_WH_MIN, ZMD_ACK_WH_MAX = 1.5, 3.0
ZMD_ACK_WHITE_MIN = 0.05
ZMD_ACK_Y1_FRAC = 0.92               # 下沿必须在底部控制条**之上**（排除开始任务）
ZMD_ACK_Y0_FRAC = 0.50               # 上半屏不放（模态框按钮在下半屏）
ZMD_ACK_X_FRAC = 0.45                # 右半边（「知道了」在右侧）
ZMD_ACK_RATIO = 0.5                  # 第二候选 >= 最优的一半 => 歧义，不点
ZMD_ACK_CLICK_TRIES = 3


def _zmd_prog_logdir(logdir=None):
    """zmd 的 debug 目录：Program.logdir 可覆盖，默认 ZMD_LOGDIR。"""
    try:
        prog = programs_mod.get("zmd")
    except (KeyError, ValueError):
        prog = None
    return Path(logdir or getattr(prog, "logdir", None) or ZMD_LOGDIR)


def zmd_app_log_path(logdir=None):
    """最新一份**应用日志** `<date>-<n>.log`（每次启动重建，故属于当前实例）。

    按 (日期, 序号) 取最大：序号是当天启动次数的自增计数器。
    找不到返回 None（首次启动、日志被手动清掉等），调用方必须容忍。
    """
    d = _zmd_prog_logdir(logdir)
    best = None
    try:
        names = list(d.iterdir())
    except OSError:
        return None
    for p in names:
        m = ZMD_APP_LOG_RX.match(p.name)
        if not m:
            continue
        key = (m.group(1), int(m.group(2)))
        if best is None or key > best[0]:
            best = (key, p)
    return best[1] if best else None


def _zmd_app_log_text(logdir=None, nbytes=1 << 20):
    p = zmd_app_log_path(logdir)
    if p is None:
        return ""
    return _zmd_read_tail(p, nbytes) or ""


def zmd_update_phase(tauri_text, app_text, baseline=None):
    """**纯函数**：从两段日志文本判定自我更新现在处于哪一阶段（可离线单测）。

    返回 `{"phase": str, "evidence": [行...], "zip": str|None}`，phase 取值：

      `idle`        没有更新活动（**默认放行**）
      `detecting`   只看到「找到匹配的 Release」（可能只是版本检查，宽限 90s）
      `downloading` 已开始下 MaaEnd 本体更新包、还没下完
      `installing`  下载完成 / 正在解压替换（随时会重启）
      `finished`    应用日志出现「检测到刚更新完成」⇒ 已重启，弹窗可能在场

    判定顺序：**最后一条事件说了算**（重新从 downloading 走一遍时不会被
    上一轮的 install 行污染）；`finished` 优先级最高（它就是重启后的状态）。
    `baseline` 给定时丢弃时间戳早于它的行（无时间戳的行一并丢弃 —— 它们
    是上一行的延续，宁可少判也不要误判）。
    """
    ev = []
    phase = "idle"
    zipname = None
    for line in (tauri_text or "").splitlines():
        if not line.strip():
            continue
        if baseline is not None:
            ts = zmd_parse_ts(line)
            if ts is None or ts < baseline:
                continue
        if re.search(ZMD_UPD_INSTALL, line):
            phase = "installing"
            ev.append(line)
        elif ZMD_UPD_ZIP_MARK in line and re.search(ZMD_UPD_DL_DONE, line):
            phase = "installing"
            ev.append(line)
        elif ZMD_UPD_ZIP_MARK in line and re.search(ZMD_UPD_DL_START, line):
            phase = "downloading"
            ev.append(line)
            m = re.search(r"([\w.\-]*" + re.escape(ZMD_UPD_ZIP_MARK) + r"[\w.\-]*\.zip)",
                          line, re.I)
            if m:
                zipname = m.group(1)
        elif re.search(ZMD_UPD_DETECT, line):
            if phase == "idle":
                phase = "detecting"
            ev.append(line)

    for line in (app_text or "").splitlines():
        if not re.search(ZMD_UPD_FINISHED, line):
            continue
        if baseline is not None:
            ts = zmd_parse_ts(line)
            if ts is not None and ts < baseline:
                continue
        phase = "finished"
        ev.append(line)

    return {"phase": phase, "evidence": ev[-4:], "zip": zipname}


def zmd_update_baseline(now=None, lookback=ZMD_UPDATE_LOOKBACK):
    """闸门的时间地板：只看最近 lookback 秒内的日志行。"""
    now = now or datetime.now()
    return now - timedelta(seconds=float(lookback))


def _zmd_update_probe(logdir=None, baseline=None):
    """读两份日志并判阶段（在线路径与单跑共用）。"""
    tauri = _zmd_read_tail(_zmd_log_path(), ZMD_SELFCHECK_BYTES) or ""
    app = _zmd_app_log_text(logdir)
    return zmd_update_phase(tauri, app, baseline)


def zmd_update_wait(state, log, max_wait=ZMD_UPDATE_WAIT_SECONDS, lookback=None):
    """节点 5 用：只读日志，等「下载 / 安装 / 重启」收敛。**不点任何东西**。

    返回 `{"state": "ready"|"timeout", "phase":..., "waited":秒, "evidence":[...]}`。
    超时**不**自动放行：由节点 5 判失败并把 phase 写进 note（INV-30）。
    """
    baseline = zmd_update_baseline(lookback=lookback if lookback is not None
                                   else ZMD_UPDATE_LOOKBACK)
    t0 = time.time()
    seen, detect_since = None, None
    log(f"  [更新闸门] 先查自我更新（只读日志，不点界面）")
    log(f"    应用日志：{zmd_app_log_path()}")
    log(f"    下载日志：{_zmd_log_path()}")
    while True:
        info = _zmd_update_probe(baseline=baseline)
        ph = info["phase"]
        if ph != seen:
            log(f"    阶段：{ph}")
            if info["evidence"]:
                log(f"    证据：{_zmd_clean(info['evidence'][-1])[:160]}")
            seen = ph
        if ph == "idle":
            log(f"  [更新闸门] 无更新活动（+{time.time() - t0:.0f}s）—— 继续")
            return {"state": "ready", "phase": ph, "waited": round(time.time() - t0, 1),
                    "evidence": []}
        if ph == "finished":
            log(f"  [更新闸门] 更新已完成并重启（+{time.time() - t0:.0f}s）；"
                f"弹窗留给节点 6 处理")
            return {"state": "ready", "phase": ph, "waited": round(time.time() - t0, 1),
                    "evidence": [_zmd_clean(x)[:120] for x in info["evidence"]]}
        if ph == "detecting":
            if detect_since is None:
                detect_since = time.time()
            elif time.time() - detect_since > ZMD_UPDATE_DETECT_GRACE:
                log("  [注] 只有「找到匹配的 Release」、没有下载动作 ——"
                    " 判为与本闸门无关的版本检查，放行")
                return {"state": "ready", "phase": "detecting_stale",
                        "waited": round(time.time() - t0, 1),
                        "evidence": [_zmd_clean(x)[:120] for x in info["evidence"]]}
        waited = time.time() - t0
        if waited > max_wait:
            return {"state": "timeout", "phase": ph, "waited": round(waited, 1),
                    "evidence": [_zmd_clean(x)[:120] for x in info["evidence"]]}
        time.sleep(ZMD_UPDATE_POLL)


def zmd_locate_ack(frame_rgb, log=None):
    """在帧里找「知道了」那个绿色按钮。返回 `{"button": dict|None, ...}`。

    ⚠️ 与 `zmd_locate_start` **不能共用判据**：那个按钮在底部 15% 带、
    宽高比 2~4；这个在模态框里、宽高比约 1.9、下沿**必须高于**底部控制条
    （否则会把被遮罩压暗的「开始任务」当目标 —— 实测它仍有 132 格绿）。
    """
    a = np.asarray(frame_rgb, dtype=np.int16)
    if a.ndim != 3 or a.shape[2] < 3:
        raise GuardFailure(
            "INV-24", f"「知道了」定位失败：期望 HxWx3 的 RGB 帧，收到 shape={a.shape}")
    H, W = a.shape[:2]
    mask = zmd_green_mask(a)
    comps = zmd_components(mask)
    step2 = ZMD_COMP_STEP * ZMD_COMP_STEP

    cands, rejected = [], []
    for c in comps:
        x0, y0, x1, y1 = c["box"]
        w, h = c["w"], c["h"]
        area = c["cells"] * step2
        reason = None
        if c["cells"] < ZMD_ACK_MIN_CELLS:
            reason = f"格数 {c['cells']} < {ZMD_ACK_MIN_CELLS}"
        elif not (ZMD_ACK_W_MIN <= w <= ZMD_ACK_W_MAX):
            reason = f"宽 {w} 不在 [{ZMD_ACK_W_MIN}, {ZMD_ACK_W_MAX}]"
        elif not (ZMD_ACK_H_MIN <= h <= ZMD_ACK_H_MAX):
            reason = f"高 {h} 不在 [{ZMD_ACK_H_MIN}, {ZMD_ACK_H_MAX}]"
        elif not (ZMD_ACK_WH_MIN <= w / float(h) <= ZMD_ACK_WH_MAX):
            reason = f"宽高比 {w / float(h):.2f} 不在 [{ZMD_ACK_WH_MIN}, {ZMD_ACK_WH_MAX}]"
        elif y1 > H * ZMD_ACK_Y1_FRAC:
            reason = f"y1={y1} 踩到底部带（需 <= {int(H * ZMD_ACK_Y1_FRAC)}，那是开始任务）"
        elif y0 < H * ZMD_ACK_Y0_FRAC:
            reason = f"y0={y0} 在上半屏（需 >= {int(H * ZMD_ACK_Y0_FRAC)}）"
        elif c["center"][0] < W * ZMD_ACK_X_FRAC:
            reason = f"x={c['center'][0]} 在左半边（需 >= {int(W * ZMD_ACK_X_FRAC)}）"
        if reason is not None:
            rejected.append((c, reason))
            continue
        sub = a[y0:y1, x0:x1]
        n_px = sub.shape[0] * sub.shape[1]
        white = int((((sub[:, :, 0] >= ZMD_WHITE_MIN)
                      & (sub[:, :, 1] >= ZMD_WHITE_MIN)
                      & (sub[:, :, 2] >= ZMD_WHITE_MIN))).sum())
        wf = (white / n_px) if n_px else 0.0
        if wf < ZMD_ACK_WHITE_MIN:
            rejected.append((c, f"白占比 {wf:.3f} < {ZMD_ACK_WHITE_MIN}（无文字）"))
            continue
        cands.append({"box": (x0, y0, x1, y1), "center": c["center"],
                      "w": w, "h": h, "area": area, "white_frac": wf,
                      "cells": c["cells"]})

    out = {"button": None, "candidates": cands,
           "rejected": [(c["box"], r) for c, r in rejected[:6]],
           "frame_size": (W, H), "reason": None}
    if not cands:
        out["reason"] = "没有符合 ack 形态的绿块"
        if log:
            log(f"    [zmd] 未找到「知道了」（连通域 {len(comps)} 个，"
                f"被拒 {len(rejected)} 个）")
            for box, r in out["rejected"][:4]:
                log(f"      box={box} {r}")
        return out

    cands.sort(key=lambda c: -c["area"])
    best = cands[0]
    if len(cands) > 1 and cands[1]["area"] >= best["area"] * ZMD_ACK_RATIO:
        out["reason"] = (f"歧义：第二候选 area={cands[1]['area']} "
                         f">= {ZMD_ACK_RATIO} x 最优 {best['area']}")
        if log:
            log(f"    [zmd] [!!] {out['reason']} —— 不点")
        return out
    out["button"] = best
    if log:
        log(f"    [zmd] 「知道了」box={best['box']} center={best['center']} "
            f"白占比={best['white_frac']:.3f} 帧={W}x{H}")
    return out


def zmd_update_dismiss(state, log, max_tries=ZMD_ACK_CLICK_TRIES):
    """节点 6 用：若更新完成弹窗在场，点掉它。返回 dict（state 见下）。

      `skipped`    最新应用日志里没有「检测到刚更新完成」⇒ 没发生过更新
      `no_modal`   有标记但画面上没有「知道了」⇒ 弹窗已不在（**立即返回**）
      `dismissed`  找到并点掉了
      `failed`     点了点不掉 / 抓帧或点击被不变量拦下

    ⚠️ 双证据才点：日志标记 **且** 帧里 ack 形态绿块。只有按钮没有标记时
    **不点** —— 那个绿块可能是别处同款元素（绿色是 MaaEnd 的状态色首选）。
    """
    app_path = zmd_app_log_path()
    app_text = _zmd_app_log_text()
    if not re.search(ZMD_UPD_FINISHED, app_text):
        log(f"  [更新闸门] 无「更新完成」标记（{app_path}）—— 无需处理")
        return {"state": "skipped", "app_log": str(app_path)}

    from ...steps import context   # 函数内 import：避免 apps <-> steps 的导入环

    log(f"  [更新闸门] 应用日志有「检测到刚更新完成」—— 检查是否有「知道了」弹窗")
    for attempt in range(1, max_tries + 1):
        hwnd = context.require_hwnd(state, log=None)
        if not hwnd:
            log(f"    第 {attempt} 次：窗口还没回来 —— 等 3s")
            time.sleep(3.0)
            continue
        try:
            input_mod.ensure_foreground(hwnd, log=None)
            f = capture_mod.grab_frame(hwnd)
        except GuardFailure as e:
            log(f"    [!!] [{e.invariant}] {e.detail.splitlines()[0]}")
            if attempt == max_tries:
                return {"state": "failed", "why": f"{e.invariant}: {e.detail[:200]}"}
            time.sleep(2.0)
            continue

        info = zmd_locate_ack(f.rgb, log=log)
        btn = info["button"]
        if btn is None:
            log(f"  [更新闸门] 弹窗**已不在**（{info['reason']}）—— 直接继续")
            return {"state": "no_modal", "reason": info["reason"],
                    "frame_size": list(info["frame_size"])}

        dst = state.shot_path(f"zmd-update-ack-{attempt}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        from PIL import Image
        Image.fromarray(f.rgb).save(dst)
        state.add_shot("6", dst)
        log(f"    [落盘] {os.path.relpath(dst, state.run_dir)}  ← 请肉眼复核")

        sx, sy = f.screen_xy(*btn["center"])
        state.set("hwnd", hwnd)
        log(f"    点击「知道了」({sx},{sy}) 第 {attempt}/{max_tries} 次")
        try:
            input_mod.guarded_click(hwnd, sx, sy, log=log)
        except GuardFailure as e:
            log(f"    [!!] [{e.invariant}] {e.detail.splitlines()[0]}")
            if attempt == max_tries:
                return {"state": "failed", "why": f"{e.invariant}: {e.detail[:200]}"}
            time.sleep(2.0)
            continue

        time.sleep(1.0)
        try:
            h2 = context.require_hwnd(state, log=None) or hwnd
            f2 = capture_mod.grab_frame(h2)
        except GuardFailure as e:
            log(f"    [注] 点后复抓帧失败（{e.invariant}）：无法确认弹窗消失")
            return {"state": "dismissed", "confirmed": False, "clicked": [sx, sy]}
        after = zmd_locate_ack(f2.rgb)
        if after["button"] is None:
            log("    [OK] 「知道了」已消失 —— 界面可继续")
            return {"state": "dismissed", "confirmed": True, "clicked": [sx, sy],
                    "box": list(btn["box"])}
        log("    [!!] 点后仍能定位到「知道了」—— 重试")
    return {"state": "failed", "why": f"{max_tries} 次点击后弹窗仍在"}

