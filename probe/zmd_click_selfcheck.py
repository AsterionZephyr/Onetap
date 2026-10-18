# -*- coding: utf-8 -*-
"""离线验证 zmd_click_and_confirm 的三级证据（不碰真实窗口/日志）。

重点回归一个**曾经静默的 bug**：frame_changed() 返回的是 tuple (changed, why)，
原实现写 `changed = frame_changed(...)` 后判 `changed is True`，
恒为 False ⇒ **弱证据分支从来没生效过**，永远落到 "no_effect"。
"""
import sys, types
sys.path.insert(0, "E:/TOOLS/ScriptsGames/Onetap")  # 正斜杠：避免转义踩坑

import numpy as np

from orchestrator import apps, capture as capture_mod, input as input_mod
from orchestrator.steps import context as ctx_mod

Z = apps.get("zmd")
Z.ZMD_START_CONFIRM_SECONDS = 0.05
Z.ZMD_POLL_SECONDS = 0.01
Z.ZMD_CLICK_RETRIES = 1

FAILS = []
def chk(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond: FAILS.append(msg)

class FakeFrame:
    left = 0
    top = 0
    def __init__(self, rgb):
        self.rgb = rgb
    def screen_xy(self, cx, cy):
        return (cx, cy)

class FakeZW:
    def __init__(self, text=""):
        self._text = text
    def poll(self):
        pass
    def text(self):
        return self._text

# 桩：定位 / 抓帧 / 点击 / hwnd 全部替掉，只测判定分支
Z.zmd_locate_start = lambda rgb, log=None: {
    "button": {"box": (0, 0, 10, 10), "center": (5, 5), "area": 100},
    "candidates": [1]}
ctx_mod.require_hwnd = lambda state, log=None: 999
clicks = []
input_mod.guarded_click = lambda hwnd, x, y, dry_run=False, log=None: clicks.append((x, y))

class State:
    dry_run = False
    def set(self, k, v):
        pass

base_rgb = np.zeros((60, 200, 3), np.uint8)
frame = FakeFrame(base_rgb)
log = lambda s: None

# A. 日志拿到「任务已接单」=> started（最强证据，不看画面）
zw = FakeZW("[2026-10-18][22:12:49][INFO][mxu_lib::commands::maa_agent] "
            "[start_tasks] All tasks submitted, total: 12 task_ids")
kind, detail = Z.zmd_click_and_confirm(State(), frame, log, zw, None)
print("A ->", kind, "|", detail[:70])
chk(kind == "started", "A 日志有 start_tasks => started")
chk(len(clicks) == 1, "A 只点一次")

# B. 日志出现 pretask 非零退出 => pretask_failed（明确的失败）
zw = FakeZW("[pretask:go-service][stdout] ... run_pretask finished with exit code: 1")
kind, detail = Z.zmd_click_and_confirm(State(), frame, log, zw, None)
print("B ->", kind, "|", detail[:70])
chk(kind == "pretask_failed", "B pretask 失败 => pretask_failed")

# C. 日志无信号，但**画面变了** => started_unconfirmed_log（弱证据，曾经永远走不到）
capture_mod.grab_frame = lambda hwnd, strict_content=True: FakeFrame(
    np.full((60, 200, 3), 255, np.uint8))
zw = FakeZW("")
kind, detail = Z.zmd_click_and_confirm(State(), frame, log, zw, None)
print("C ->", kind, "|", detail[:70])
chk(kind == "started_unconfirmed_log", "C 画面变化 => started_unconfirmed_log（tuple 解包已修）")

# D. 日志无信号、画面也没变 => no_effect
capture_mod.grab_frame = lambda hwnd, strict_content=True: FakeFrame(base_rgb.copy())
zw = FakeZW("")
kind, detail = Z.zmd_click_and_confirm(State(), frame, log, zw, None)
print("D ->", kind, "|", detail[:70])
chk(kind == "no_effect", "D 日志与画面都没变 => no_effect")

print("")
print("PASSED" if not FAILS else "FAILED: %r" % FAILS)
sys.exit(0 if not FAILS else 1)
