"""orchestrator.py — 编排层：按顺序运行多个目标程序完成任务

用户目标：ok-ww 先运行，然后 ok-nte。
**不检查游戏状态**（用户明确要求）。

关键设计（见 HANDOFF.md §9）：
  1. 串行独占：一次只跑一个
  2. 三种终止要区分：正常完成（自行退出）/ 失败 / 超时
  3. **证据不足时报「未知」，绝不默认「成功」**（INV-30）
  4. 每步都有校验；不过即停手
  5. 全程记录，产出可复核的日志

用法：
  python orchestrator.py --dry-run          # 只演练，不真点
  python orchestrator.py                    # 真实执行
  python orchestrator.py --only ok-ww       # 只跑指定程序
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ctypes
import ctypes.wintypes as wt

import numpy as np
from PIL import Image

import capture as C
from template_probe import match_template
from nte_main import all_hits
import targets as T

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = C.user32
OUT = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe\orch")
OUT.mkdir(exist_ok=True)


# ---------------------------------------------------------------- 工具

PUL = ctypes.POINTER(ctypes.c_ulong)


class MI(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("md", ctypes.c_ulong), ("fl", ctypes.c_ulong),
                ("t", ctypes.c_ulong), ("ex", PUL)]


class IN(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MI)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def click(x, y):
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y)
    time.sleep(0.1)
    nx, ny = int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))
    for f in (0x0001 | 0x8000, 0x0002, 0x0004):
        i = IN(); i.type = 0
        i.mi.dx, i.mi.dy, i.mi.fl = nx, ny, f
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(IN))
        time.sleep(0.05)


def c2s(hwnd, cx, cy):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P(cx, cy); user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def top_at(x, y):
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    return user32.GetAncestor(user32.WindowFromPoint(P(x, y)), 2)


class R(ctypes.Structure):
    _fields_ = [("l", wt.LONG), ("t", wt.LONG), ("r", wt.LONG), ("b", wt.LONG)]


def procs():
    d = {}
    for n in ["pythonw", "ok-ww", "ok-nte"]:
        o = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {n}.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace").stdout
        d[n] = [l.split('","')[1] for l in o.splitlines() if l.startswith('"')]
    return d


def find_window(title_sub, require_long_title=False, exclude_class=None):
    """按标题子串找可见主窗口。

    参数
      require_long_title: 只接受"长标题"（第二层的特征，如
                          `OK-WW v3.6.7 China  - OK-WW`），排除第一层的短标题
                          （`ok-nte` / `ok-ww`）。
      exclude_class     : 排除的窗口类（如 'Tauri Window' = 第一层）。

    ⚠️ 实测教训：ok-nte 的第一层（Tauri Window, 标题 `ok-nte`）与第二层
    （Qt, 标题 `ok-nte v1.4.6 China  - ok-nte`）**都会被标题子串匹配到**；
    编排曾误取第一层，导致身份校验 0.4224 失败。
    """
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, b, n + 2)
            t = b.value
            if title_sub.lower() in t.lower():
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(h, cls, 256)
                cname = cls.value
                if exclude_class and exclude_class.lower() in cname.lower():
                    return True
                if require_long_title and not ("-" in t and len(t) > 20):
                    return True
                r = R(); user32.GetWindowRect(h, ctypes.byref(r))
                w, hh = r.r - r.l, r.b - r.t
                if w > 200 and hh > 200 and user32.IsWindowVisible(h):
                    res.append((h, t, w, hh))
        return True

    user32.EnumWindows(cb, 0)
    return res


def find_layer2(title_sub, exclude_class="Tauri Window"):
    """专取第二层窗口：排除第一层类，且偏好长标题。"""
    ws = find_window(title_sub, require_long_title=True, exclude_class=exclude_class)
    if ws:
        return ws
    # 回退：仅按类排除
    return find_window(title_sub, exclude_class=exclude_class)


# ---------------------------------------------------------------- 单目标流程

class Result:
    def __init__(self, name):
        self.name = name
        self.phase = "init"
        self.verdict = "UNKNOWN"        # SUCCESS / FAILED / TIMEOUT / UNKNOWN
        self.notes = []
        self.t0 = time.time()

    def note(self, s):
        self.notes.append(s)
        log(f"    {s}")

    def finish(self, verdict, why):
        self.verdict = verdict
        self.phase = "done"
        self.elapsed = time.time() - self.t0
        log(f"  ==> {self.name}: {verdict}  ({why})  用时 {self.elapsed:.0f}s")
        return self

    def to_dict(self):
        return {"name": self.name, "verdict": self.verdict,
                "elapsed": round(getattr(self, "elapsed", 0), 1),
                "notes": self.notes}


def detect_hamburger(frame, x0=0, x1=70, y0=0, y1=220):
    """程序化定位 ☰ 菜单图标（三条等距水平亮线）。

    ⚠️ 实测教训（INV-34/38）：**不要用固定的 ☰ 截图当身份锚点**。
    实测同一程序在**同一尺寸**下，☰ 的匹配分从 1.0000 掉到 0.55 ——
    因为 ok-ww 启动后会**异步加载用户头像**等元素，导致左上角区域的
    像素内容与"刚启动时"不同，而静态裁剪的模板对此不具备鲁棒性。
    程序化特征检测（找三条等距横线）每次都能正确定位。
    """
    sub = frame[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    g = sub.astype(np.float32).mean(axis=2)
    bright = g > 120
    rowsum = bright.sum(axis=1)
    lines = [i for i, v in enumerate(rowsum) if v >= 8]
    if len(lines) < 3:
        return None
    groups, s, prev = [], lines[0], lines[0]
    for i in lines[1:]:
        if i - prev > 2:
            groups.append((s, prev)); s = i
        prev = i
    groups.append((s, prev))
    for i in range(len(groups) - 2):
        a, b, c = groups[i], groups[i + 1], groups[i + 2]
        ga, gb = b[0] - a[1], c[0] - b[1]
        if abs(ga - gb) <= 2 and 2 <= ga <= 10:
            band = bright[a[0]:c[1] + 1]
            cols = np.where(band.any(axis=0))[0]
            if len(cols) < 6:
                continue
            return (x0 + int(cols.min()), y0 + a[0],
                    x0 + int(cols.max()), y0 + c[1])
    return None


def identity_ok(frame, cfg):
    """身份校验：优先**程序化定位**，回退到静态模板。

    返回 (ok, score_or_1, pos, how)。
    """
    # 1) 程序化：☰ 菜单
    box = detect_hamburger(frame)
    if box:
        x0, y0, x1, y1 = box
        # 交叉验证：该区域应与已知 ☰ 模板形状相近（宽>高、扁平）
        w, h = x1 - x0 + 1, y1 - y0 + 1
        if 8 <= w <= 40 and 8 <= h <= 30 and w >= h:
            return True, 1.0, ((x0 + x1) // 2, (y0 + y1) // 2), "程序化☰"

    # 2) 回退：静态模板
    ident = cfg["anchors"]["identity"]
    if ident is not None:
        s, x, y = match_template(frame, ident)
        th, tw, _ = ident.shape
        return (s >= T.ACCEPT), s, (x + tw // 2, y + th // 2), "模板"
    return False, 0.0, None, "无可用方法"


def normalize_window_size(hwnd, cfg, w, h):
    """把窗口调整到**资产采集时的尺寸**。

    ⚠️ 实测根因（INV-39）：**UI 内容随窗口尺寸变化** ——
    \"每日任务\"行在 1823x1000 下锚点匹配 1.0000，在 2560x1400 下掉到 0.55 以下。
    而程序会**持久化窗口几何**（ok-ww 的 `_ok.json` 里 window_width/height），
    所以每次启动的尺寸都可能不同（实测出现过 1458x800 / 1823x1000 /
    1875x1250 / 2279x1250 / 2560x1400）。

    ⇒ 编排层在抓帧前**主动把窗口设成配准尺寸**，使图像资产始终有效。
      这是比"让锚点适应所有尺寸"更可靠的做法。
    """
    want = cfg.get("window_size")
    if not want:
        return
    r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    cur_w, cur_h = r.r - r.l, r.b - r.t
    if (cur_w, cur_h) == tuple(want):
        return
    log(f"      归一化窗口尺寸 {cur_w}x{cur_h} -> {want[0]}x{want[1]}"
        f"（资产按此尺寸采集）")
    user32.MoveWindow(hwnd, r.l, r.t, want[0], want[1], True)
    time.sleep(1.5)


def wait_for_layer2(name, cfg, timeout=180):
    """等待第二层窗口出现（第一层会自动放行）。

    ⚠️ 实测踩坑：
      1. `find_layer2('ok-nte')` 会匹配到**任何标题含 'ok-nte' 的窗口**，
         例如编辑器里打开了 `OK-NTE-ADAPTATION.md` 的窗口（实测被抓到，
         导致置前台失败）。故要求标题形如 `<程序名> vX.Y.Z ... - <程序名>`。
      2. 超时 **90s 不够**：在**紧接另一个程序之后**启动时（ok-ww 刚退出），
         实测 ok-nte 超过 90s 仍未出现窗口；单独启动时约 20s。
         故放宽到 180s。
    """
    import re
    title_sub = cfg["title_regex"]
    ver_pat = re.compile(rf"^{re.escape(title_sub)}\s+v\d+", re.I)
    log(f"  等待第二层窗口（最多 {timeout}s，第一层会自动放行）")
    t0 = time.time()
    while time.time() - t0 < timeout:
        # 先用严格模式（标题以 <name> vX.Y 开头）
        ws = [w for w in find_window(title_sub, exclude_class="Tauri Window")
              if ver_pat.match(w[1])]
        if not ws:
            ws = [w for w in find_window(title_sub, require_long_title=True,
                                         exclude_class="Tauri Window")
                  if ver_pat.match(w[1])]
        for h, t, w, hh in ws:
            log(f"  第二层就绪: [{t}] {w}x{hh}")
            return h, w, hh
        time.sleep(2)
    return None, 0, 0


def grab(hwnd):
    r = R(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.r - r.l, r.b - r.t
    got = C.capture_region(r.l, r.t, w, h)
    if got is None:
        return None, None, None, None
    d, fw, fh = got
    f = np.frombuffer(d, dtype=np.uint8).reshape(fh, fw, 4)[:, :, [2, 1, 0]]
    return f, r, fw, fh


def frame_is_black(f, thresh=15):
    """判断帧是否近乎全黑。直接用 RGB 数组，不再转回 bytes。"""
    if f is None or f.size == 0:
        return True
    m = f.reshape(-1, 3).mean(axis=0)      # 每通道均值
    return float(m.sum()) < thresh


def frame_color_count(f, step=None):
    """粗略统计采样到的色彩种类（用于内容校验）。"""
    n = f.shape[0] * f.shape[1]
    step = step or max(1, n // 4000)
    flat = f.reshape(-1, 3)[::step]
    q = (flat // 8).astype(np.int32)
    return len({(int(a), int(b), int(c)) for a, b, c in q})


def force_foreground(hwnd, tries=4):
    """把窗口提到前台，带多种回退策略。

    背景：`SetForegroundWindow` 受「前台锁」限制 —— 若调用进程本身不是前台进程，
    系统可能只闪烁任务栏而**不真正**交出前台（返回值仍为 1）。
    实测：同一窗口，直接调用可能失败，稍后重试则成功；故必须**重试 + 验证**。
    """
    for i in range(tries):
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        time.sleep(0.4)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.6)
        if user32.GetForegroundWindow() == hwnd:
            return True, i + 1
        # 回退：AttachThreadInput 到当前前台线程后再设置
        try:
            fg = user32.GetForegroundWindow()
            k32 = ctypes.windll.kernel32
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            my_tid = k32.GetCurrentThreadId()
            user32.AttachThreadInput(my_tid, fg_tid, True)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(my_tid, fg_tid, False)
            time.sleep(0.6)
            if user32.GetForegroundWindow() == hwnd:
                return True, i + 1
        except Exception:
            pass
        # 回退：BringWindowToTop
        try:
            user32.BringWindowToTop(hwnd)
            time.sleep(0.4)
            if user32.GetForegroundWindow() == hwnd:
                return True, i + 1
        except Exception:
            pass
    return False, tries


def settle_between_targets(seconds=10):
    """在两个目标之间等待桌面稳定。

    ⚠️ 实测教训（INV-42）：**紧接上一个程序退出后启动下一个程序时，置前台会失败**
    （实测 ok-nte 4 次尝试全败，最终 FAILED）；而**单独启动同一程序时第 1 次就成功**。
    成因：上一个程序的窗口刚消失，Windows 的前台锁短暂拒绝焦点切换。
    ⇒ 编排在两个目标之间显式等待，让桌面状态稳定。
    """
    if seconds <= 0:
        return
    log(f"\n  [间隔] 等待桌面稳定 {seconds}s（避免前台锁，见 INV-42）")
    time.sleep(seconds)


def wait_until_ready(name, cfg, hwnd, timeout=180):
    """等待程序真正就绪（不只是窗口出现）。

    ⚠️ 实测教训：
      1. ok-nte 在窗口出现后仍显示「正在启动, 120秒后超时.」遮罩，界面未渲染。
      2. **身份判定必须与"加载中的界面"无关**：ok-ww 启动后会异步加载用户头像，
         期间左上角像素随之改变 —— 用静态 ☰ 截图当锚点会从 1.0000 掉到 0.55。
         故改用**程序化定位 ☰**（见 identity_ok）。

    返回 (ok, frame)。
    """
    log(f"      等待就绪（最多 {timeout}s，需身份判定连续 3 次通过）")
    t0 = time.time()
    streak = 0
    last = 0.0
    while time.time() - t0 < timeout:
        f, r, fw, fh = grab(hwnd)
        if f is None:
            time.sleep(2)
            continue
        ok, sc, pos, how = identity_ok(f, cfg)
        last = sc
        if ok:
            streak += 1
            log(f"        +{time.time()-t0:5.0f}s {how} {pos} (连续 {streak}/3)")
            if streak >= 3:
                log(f"      就绪")
                return True, f
        else:
            if streak:
                log(f"        +{time.time()-t0:5.0f}s 判定失败（连续性中断）")
            streak = 0
        time.sleep(2)
    log(f"      就绪等待超时（最后得分 {last:.4f}）")
    return False, None


def _report_nte_failures(WV, text):
    """完成后打印 ok-nte 的单项失败原文（**不参与判定**，仅告知）。

    用户要求：ok-nte 的单项失败与本项目无关；只关注是否完成。
    ⚠️ 这里传入的 text 已经是"本次运行"的窗口，故不再二次分段（latest_only=False）。
    """
    if not hasattr(WV, "extraction_summary"):
        return
    try:
        succ, fail, skip = WV.extraction_summary(text, latest_only=False)
    except TypeError:
        succ, fail, skip = WV.extraction_summary(text)
    if succ:
        log(f"      逐项成功 {len(succ)} 项: {succ}")
    if skip:
        log(f"      跳过 {len(skip)} 项: {skip}")
    if fail:
        log(f"      ⚠ 失败 {len(fail)} 项（不影响流程判定）: {fail}")
    else:
        log(f"      无失败项")


def run_target(name, dry=False, task_timeout=1200):
    cfg = T.TARGETS[name]
    res = Result(name)
    log(f"\n{'='*68}")
    log(f"目标：{name}")
    log(f"{'='*68}")

    # 0) 是否已在运行
    p = procs()
    if p["pythonw"]:
        res.note(f"检测到已有 pythonw 在运行（{p['pythonw']}）—— 独占式前提要求先清理")

    # 1) 启动
    res.phase = "launch"
    log(f"  [1] 启动 {cfg['exe']}")
    if not dry:
        try:
            subprocess.Popen([cfg["exe"]], cwd=cfg["cwd"])
        except Exception as e:
            return res.finish("FAILED", f"启动失败：{e}")
    else:
        log("      [DRY] 跳过实际启动")

    if dry:
        # dry-run 只检查当前是否已有窗口
        ws = find_layer2(cfg["title_regex"]) or []
        if not ws:
            return res.finish("UNKNOWN", "DRY: 未启动，也无现存窗口")
        hwnd, w, h = ws[0][0], ws[0][2], ws[0][3]
    else:
        hwnd, w, h = wait_for_layer2(name, cfg)
        if not hwnd:
            return res.finish("FAILED", "第二层窗口未在超时内出现")

    # 2) 置前台 + 校验
    res.phase = "focus"
    log(f"  [2] 置前台 + 校验")
    ok_fg, n_try = force_foreground(hwnd)
    log(f"      置前台{'成功' if ok_fg else '失败'}（第 {n_try} 次尝试）")
    if not ok_fg:
        return res.finish("FAILED", f"置前台失败（{n_try} 次尝试均未取得前台）")

    # 2a) 归一化窗口尺寸（UI 随尺寸变化 => 必须回到资产采集时的尺寸）
    if not dry:
        normalize_window_size(hwnd, cfg, w, h)
        ws2 = find_layer2(cfg["title_regex"]) or []
        if ws2:
            hwnd = ws2[0][0]
            w, h = ws2[0][2], ws2[0][3]
        force_foreground(hwnd)

    f, r, fw, fh = grab(hwnd)
    if f is None:
        return res.finish("FAILED", "抓帧失败")
    if (fw, fh) != (w, h):
        return res.finish("FAILED", f"INV-1 帧尺寸 {fw}x{fh} != 窗口 {w}x{h}")
    if frame_is_black(f):
        return res.finish("FAILED", "帧近乎全黑（INV-13）")
    res.note(f"帧 {fw}x{fh} 校验通过（色彩数 {frame_color_count(f)}）")

    # 2b) 等待真正就绪（窗口出现 ≠ 界面可用）
    res.phase = "ready"
    log(f"  [2b] 等待就绪")
    ready, f2 = wait_until_ready(name, cfg, hwnd)
    if not ready:
        return res.finish("FAILED", "程序未在超时内就绪（可能仍在加载）")
    if f2 is not None:
        f = f2

    # 3) 身份校验
    res.phase = "identity"
    ok_id, s_id, pos_id, how_id = identity_ok(f, cfg)
    log(f"  [3] 身份校验 {how_id} pos={pos_id} score={s_id:.4f}")
    if not ok_id:
        return res.finish("FAILED", f"身份校验失败（{how_id} {s_id:.4f}）—— 帧可能不是该程序")
    res.note(f"身份校验通过（{how_id}）")

    # 4) 定位动作元素（必要时先导航到任务页）
    res.phase = "locate"
    log(f"  [4] 定位动作元素")
    action = cfg["anchors"]["action"]
    page = cfg["anchors"]["page"]

    def locate_page(frame):
        return T.unique(frame, page, T.ACCEPT)

    def on_task_page(frame):
        """判定"确实在任务页"。

        ⚠️ 实测教训：**页面锚点单独不可靠**。
        ok-nte 的「关于」页上 `3_nte_daily` 曾得 0.9373（假阳性），
        导致编排误以为已在任务页而**跳过导航**，随后动作元素找不到。
        故判定必须**同时**满足：页面锚点命中 **且** 动作元素命中。
        """
        ok_p, hits_p = T.unique(frame, page, T.ACCEPT)
        if not hits_p:
            return False, hits_p, None
        if action is not None:
            ok_a, hits_a = T.unique(frame, action, T.ACCEPT)
            if not hits_a:
                return False, hits_p, None
            return (ok_p and ok_a), hits_p, hits_a
        return ok_p, hits_p, None

    in_page, hits_p, hits_a = on_task_page(f)

    # 4a) 不在任务页 -> 导航（点侧栏图标）
    if not in_page:
        log(f"      不在任务页（页面锚点命中={bool(hits_p)}，动作元素命中={bool(hits_a)}），尝试导航")
        # 侧栏在窗口最左的一条竖带内。**不依赖身份锚点的位置**（身份锚点可能是
        # 左上 ☰，其列与侧栏不同）。改为直接扫描左侧固定宽度竖带（实测 x<60）。
        SIDE_W = min(fw, 60)
        colband = f[:, :SIDE_W].astype(np.float32).mean(axis=2)
        rowsum = (colband > 110).sum(axis=1)
        active = rowsum > 2
        clusters = []
        st = None
        for yy, v in enumerate(active):
            if v and st is None:
                st = yy
            elif not v and st is not None:
                if yy - st >= 8:
                    clusters.append(((st + yy - 1) // 2, st, yy - 1))
                st = None
        if st is not None:
            clusters.append(((st + len(active) - 1) // 2, st, len(active) - 1))
        log(f"      侧栏带 x<{SIDE_W} 共 {len(clusters)} 簇: {[c[0] for c in clusters]}")

        want = cfg["nav_sidebar_y"]
        if not clusters:
            return res.finish("FAILED", "侧栏未找到任何图标")

        # 优先用"第几项"定位（对窗口缩放稳健）；无配置时回退到绝对 y
        idx = cfg.get("nav_sidebar_index")
        if idx is not None:
            # 去掉最顶部/最底部的窗口控件簇（☰ 与 通知/设置/关于）
            # 实测内容项集中在中部；取"与期望 y 同一量级"的连续段
            if idx < len(clusters):
                target = clusters[idx]
                log(f"      目标 = 侧栏第 {idx} 项 y={target[0]}"
                    f"（绝对期望 {want}，实际 {target[0]}）")
            else:
                return res.finish("FAILED",
                                  f"侧栏项不足：找到 {len(clusters)} 簇，需要第 {idx} 项")
        else:
            target = min(clusters, key=lambda c: abs(c[0] - want))
            log(f"      目标簇 y={target[0]}（配置期望 {want}）")
            if abs(target[0] - want) > 60:
                return res.finish("FAILED",
                                  f"侧栏布局与配置不符：最近图标 y={target[0]}，期望 {want}")

        icon_cx = min(30, SIDE_W // 2)
        nx, ny = c2s(hwnd, icon_cx, target[0])
        if top_at(nx, ny) != hwnd:
            return res.finish("FAILED", "侧栏导航目标被遮挡")
        log(f"      点击侧栏 (窗口内 {icon_cx},{target[0]})")
        if dry:
            res.note("DRY: 跳过导航点击")
        else:
            click(nx, ny)
            time.sleep(2.5)
            f, r, fw, fh = grab(hwnd)
            if f is None:
                return res.finish("FAILED", "导航后抓帧失败")
            in_page, hits_p, hits_a = on_task_page(f)
        if not hits_p:
            return res.finish("FAILED", f"导航后仍未找到页面锚点（点击 y={target[0]}）")
        if action is not None and not hits_a:
            return res.finish("FAILED",
                              f"导航后页面锚点命中但动作元素缺失（点击 y={target[0]}）")
        res.note(f"导航成功（点击侧栏 y={target[0]}）")
    else:
        res.note("已在任务页")

    log(f"      页面锚点 score={hits_p[0][2]:.4f} 候选={len(hits_p)}")
    if len(hits_p) > 1:
        return res.finish("FAILED", f"页面锚点不唯一（{len(hits_p)} 个）")

    if action is not None:
        if not hits_a:
            ok_a, hits_a = T.unique(f, action, T.ACCEPT)
        if not hits_a:
            return res.finish("UNKNOWN", "动作元素未找到（可能已在运行）")
        if len(hits_a) > 1:
            return res.finish("FAILED", f"动作元素不唯一（{len(hits_a)} 个）")
        ay, ax, asc = hits_a[0]
        th, tw, _ = action.shape
        bcx, bcy = ax + tw // 2, ay + th // 2
    else:
        # action=None：动作元素由**行结构扫描**得出（ok-ww，以及 v1.4.8+ 的 ok-nte）
        import ww_action as WA
        scanner = getattr(WA, cfg.get("action_scan", "find_ww_action"))
        ok_a, center, asc, ry0, ry1, why = scanner(f)
        log(f"      {name} 行结构扫描：{why}")
        if not ok_a:
            return res.finish("FAILED", f"{name} 动作元素定位失败：{why}")
        bcx, bcy = center

    log(f"      动作元素 ({bcx},{bcy}) score={asc:.4f}")

    # 5) 遮挡判定 + 点击
    res.phase = "click"
    sx, sy = c2s(hwnd, bcx, bcy)
    topw = top_at(sx, sy)
    log(f"  [5] 屏幕坐标 ({sx},{sy})  顶层={topw}  是目标={topw == hwnd}")
    if topw != hwnd:
        return res.finish("FAILED", "目标坐标被遮挡（INV-23）")

    crop = f[max(0, bcy - 30):bcy + 30, max(0, bcx - 90):bcx + 70]
    Image.fromarray(crop).save(OUT / f"{name}-about-to-click.png")

    if dry:
        res.note("DRY: 未点击")
        return res.finish("UNKNOWN", "DRY RUN 完成")

    click(sx, sy)
    time.sleep(1.5)

    # 6) 验证已启动（动作元素应消失/变化）
    res.phase = "verify_start"
    f2, r2, fw2, fh2 = grab(hwnd)
    if f2 is not None:
        if action is not None:
            s_after, _, _ = match_template(f2, action)
            log(f"  [6] 点击后动作元素 score={s_after:.4f}")
            if s_after >= T.ACCEPT:
                res.note("动作元素仍在 —— 点击可能未生效")
            else:
                res.note("动作元素已变化 —— 任务已启动")
        else:
            # ok-ww：动作元素是行内扫描得出的，没有独立模板
            # 改以「页面锚点是否仍在 + 该行是否出现运行标记」粗判
            from ww_action import find_ww_action
            ok_a2, center2, sc2, ry0, ry1, why2 = find_ww_action(f2)
            log(f"  [6] 点击后行扫描：{why2}")
            if ok_a2 and center2 == (bcx, bcy):
                res.note("按钮仍在原位 —— 点击可能未生效")
            else:
                res.note("行结构已变化 —— 任务很可能已启动")

    # 7) 等待完成（**以日志判据裁决**，而非仅看进程）
    res.phase = "wait"
    log(f"  [7] 等待完成（最多 {task_timeout}s）")
    import importlib
    vmod_name = cfg.get("verdict_module", "ww_verdict")
    WV = importlib.import_module(vmod_name)
    # 用 RunWindow / LogWatcher 记录**基线偏移**，只看本次运行新增的日志。
    # ⚠️ 不能"读全部既有日志再分段"：若上一次运行被外部强杀（无 ok:quit app），
    #    两次运行会被合并，导致本次借用上次的成功（实测假阳性）。
    watcher = WV.LogWatcher()
    base_n = len(getattr(watcher, "_baseline", getattr(watcher, "base", {})))
    log(f"      判据模块 = {vmod_name}；日志基线 {base_n} 个文件（只读新增部分）")

    def _verdict(still):
        """统一取本次运行新增日志的判定。"""
        txt = watcher.accumulated() if hasattr(watcher, "accumulated") else watcher.text()
        # RunWindow 的窗口本身已是"本次运行"，故不再做运行分段
        kw = {} if hasattr(watcher, "accumulated") else {"latest_only": False}
        return WV.verdict_from_log(txt, still_running=still, **kw), txt

    t0 = time.time()
    last_v = None
    while time.time() - t0 < task_timeout:
        p = procs()
        watcher.poll()
        (v, ev), txt = _verdict(bool(p["pythonw"]))

        if v != last_v:
            last_v = v
            log(f"      [日志判据] {v}  | {ev[0] if ev else ''}")

        if v == "SUCCESS":
            _report_nte_failures(WV, txt)
            return res.finish("SUCCESS", f"日志判据=SUCCESS；{ev[0]}")
        if v == "FAILED":
            return res.finish("FAILED", f"日志判据=FAILED；{ev[0]}")

        if not p["pythonw"]:
            # 进程消失 -> 再 poll 一次（日志可能刚轮转），然后终判
            time.sleep(1.5)
            watcher.poll()
            (v2, ev2), txt2 = _verdict(False)
            log(f"      pythonw 已消失，日志终判 = {v2}")
            if v2 in ("SUCCESS", "SUCCESS_PART"):
                _report_nte_failures(WV, txt2)
                return res.finish("SUCCESS", f"进程退出 + 日志={v2}")
            if v2 == "NO_TASK":
                return res.finish("FAILED", "进程退出但未执行任务")
            return res.finish("UNKNOWN", f"进程退出，日志判据={v2}（证据不足）")

        # 界面状态仅作记录，不用于裁决
        ws = find_layer2(cfg["title_regex"]) or []
        if ws:
            hw = ws[0][0]
            if user32.GetForegroundWindow() != hw:
                user32.SetForegroundWindow(hw)
                time.sleep(0.3)
            f3, r3, fw3, fh3 = grab(hw)
            if f3 is not None:
                st = cfg["state_fn"](f3, p)
                log(f"      界面 {json.dumps(st, sort_keys=True, default=str)}")
        time.sleep(5)

    # 超时：仍以日志裁决
    watcher.poll()
    (v, ev), txt = _verdict(True)
    if v in ("SUCCESS", "SUCCESS_PART"):
        _report_nte_failures(WV, txt)
        return res.finish("SUCCESS", f"超时前日志已判定 {v}")
    return res.finish("TIMEOUT", f"超过 {task_timeout}s；日志判据={v}")


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--task-timeout", type=int, default=1200,
                    help="单个任务等待上限（秒）。默认 1200："
                         "实测 ok-nte 一轮完整日常约需 7 分钟以上")
    ap.add_argument("--pre-clean", action="store_true",
                    help="编排开始前先强制清理目标程序的残留进程（独占式前提）")
    ap.add_argument("--no-cleanup", action="store_true",
                    help="结束后不做兜底清理")
    args = ap.parse_args()

    order = [args.only] if args.only else T.ORDER
    log("=" * 68)
    log(f"编排开始   顺序={order}   dry_run={args.dry_run}")
    log("=" * 68)

    import cleanup as CL

    if args.pre_clean:
        log("\n[前置清理] 独占式前提：清掉残留进程")
        for name in order:
            CL.cleanup(name)

    p0 = procs()
    log(f"起始进程 pythonw={p0['pythonw']} ok-ww={p0['ok-ww']} ok-nte={p0['ok-nte']}")

    results = []
    for name in order:
        res = run_target(name, dry=args.dry_run, task_timeout=args.task_timeout)

        # 兜底清理：不论成败，确保该目标不残留（除非 --no-cleanup）
        if not args.no_cleanup and not args.dry_run:
            left = CL.survey()
            residual = {k: v for k, v in left.items()
                        if v and k in (name, "pythonw")}
            if residual:
                log(f"\n  [兜底清理] 检测到残留 {residual}，执行清理")
                ok_c, _ = CL.cleanup(name)
                res.note(f"兜底清理{'成功' if ok_c else '失败'}")
            else:
                log(f"\n  [兜底清理] 无残留（程序已自行清理）")

        results.append(res)

        # 目标之间等待桌面稳定（前台锁，见 INV-42）
        if name != order[-1]:
            settle_between_targets(10)

        if res.verdict == "FAILED":
            log(f"\n!! {name} 失败，按策略中止编排")
            break

    log("\n" + "=" * 68)
    log("编排结束，结果：")
    for r in results:
        log(f"  {r.name:8s} {r.verdict:8s} {getattr(r,'elapsed',0):6.0f}s")
    log("=" * 68)

    (OUT / f"orch-{datetime.now():%Y%m%d-%H%M%S}.json").write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8")
    log(f"结果已写入 {OUT}")

    # 证据不足不是成功
    if any(r.verdict in ("UNKNOWN", "TIMEOUT") for r in results):
        return 2
    return 0 if all(r.verdict == "SUCCESS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
