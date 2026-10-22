# -*- coding: utf-8 -*-
"""离线验证 zmd_wait_completion 的「关游戏后升级证据」分支（不碰真实窗口/日志）。"""
import sys, types, io
sys.path.insert(0, r"E:\TOOLS\ScriptsGames\Onetap")
from orchestrator import verdict as V
from orchestrator import apps

# MaaEnd 的节点 8 实现已迁到 apps/zmd/__init__.py（docs/adr/0003 阶段二），
# 自检直接打它 —— 若这里改成 step8，等于在验证一个已经不存在的副本。
S = apps.get("zmd")

FAILS = []
def chk(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond: FAILS.append(msg)

class Args:  total_timeout = 120.0

class FakeZW:
    def __init__(self, script):
        self.script = list(script); self.i = -1; self.polls = 0
        self.path = "<fake>"
    def poll(self):
        self.polls += 1
        self.i = min(self.i + 1, len(self.script) - 1)
    def _cur(self): return self.script[max(self.i, 0)]
    def verdict(self, still_running=True): return self._cur()[0], self._cur()[1]
    def text(self): return self._cur()[2]

class State:
    dry_run = False
    def set(self, k, v): pass

RUN  = (V.RUNNING, [], "x")
KILL = (V.RUNNING, [], "x ... [MXU_KILLPROC] Killing process: Endfield.exe ...")
STOP = (V.SUCCESS, ["[2026-10-18][22:26:37] stop_agent_impl called for instance: yj2gs5w"], KILL[2])

S.ZMD_SETTLE_SECONDS = 1.0
S.ZMD_POLL_SECONDS = 0.01
logs = []
log = logs.append

# 情况 A：关游戏后 1 轮就出 stop => 用主判据，detail 含「日志终止信号」
mod = types.SimpleNamespace(running=lambda p: [("MaaEnd.exe", 1, "x")])
S.window = mod
zw = FakeZW([RUN, KILL, STOP, STOP])
res, detail, shot = S.zmd_wait_completion(State(), Args(), log, zw, None)
print("A ->", res, "|", detail[:80])
chk(res == S.COMPLETED, "A 结果 = COMPLETED")
chk("日志终止信号" in detail and "stop_agent_impl" in detail, "A 用的是主判据（stop_agent_impl），且 detail 不再谎称「无标记」")

# 情况 B：关游戏后始终没有 stop（进程一直活着）=> 退回辅助证据并如实写明
def gen():
    yield KILL
    while True: yield KILL
zw = FakeZW([RUN, KILL] + [KILL] * 200)
res, detail, shot = S.zmd_wait_completion(State(), Args(), log, zw, None)
print("B ->", res, "|", detail[:90])
chk(res == S.COMPLETED, "B 结果 = COMPLETED（辅助证据仍可作为完成依据）")
chk("宽限期内未看到 stop_agent" in detail, "B detail 如实写明「未看到 stop_agent」，不伪造")

# 情况 C：只有 start、进程消失 => UNKNOWN（INV-30 不默认成功）
mod2 = types.SimpleNamespace(running=lambda p: [])
S.window = mod2
zw = FakeZW([RUN])
res, detail, shot = S.zmd_wait_completion(State(), Args(), log, zw, None)
print("C ->", res, "|", detail[:70])
chk(res == S.UNKNOWN, "C 进程消失且无终止信号 => UNKNOWN")

print("\nPASSED" if not FAILS else "\nFAILED: %r" % FAILS)
sys.exit(0 if not FAILS else 1)
