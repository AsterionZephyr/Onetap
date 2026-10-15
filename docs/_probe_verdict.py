"""_probe_verdict.py — orchestrator.verdict 回归探针（ok-nte 日志判据）

**为什么需要**：这一层的失效几乎全是**静默**的 ——
判据说「成功」而实际没跑完（假阳性），或说「没有失败」而其实有失败。
两种都不会抛异常。故探针必须**双向**验证：
正向（真日志必须判对）+ 负向（证据不足必须**不报成功**）。

**重点覆盖两个已发生过的真实故障**：
  - **假阳性**：上一次运行被外部强制终止时，按 `ok:quit app` 分段会把两次
    运行合并，新一次**借用上一次的成功汇总** —— 实测点击后 1 秒就报 SUCCESS。
    ⇒ 验证 `LogWindow` 的**字节偏移**机制不受此影响。
  - **FAULT #18**：程序升级把汇总行正则打死，`success`/`skipped` 静默变 None。
    ⇒ 验证两种格式都认，且失配时显式警示。

    python -X utf8 docs/_probe_verdict.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from orchestrator import programs as P        # noqa: E402
from orchestrator import verdict as V         # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


TERMINAL = "TaskExecutor:Successfully Executed Task, Exiting Game and App!"
DAILY_END = "DailyRoutineTask:结束执行日常任务"

NEW_FMT = f"""2026-10-15 00:20:00,000 INFO TaskExecutor DailyRoutineTask:info_set success ['甲', '乙', '丙']
2026-10-15 00:20:00,001 INFO TaskExecutor DailyRoutineTask:info_set failed []
2026-10-15 00:20:00,002 INFO TaskExecutor DailyRoutineTask:info_set skipped ['丁']
2026-10-15 00:20:01,000 INFO TaskExecutor {DAILY_END}
2026-10-15 00:20:02,000 INFO TaskExecutor {TERMINAL}
"""

OLD_FMT = f"""2026-10-08 23:15:31,774 INFO TaskExecutor DailyRoutineTask:success: ['甲', '乙', '丙']
failed: []
skipped: ['丁']
2026-10-08 23:15:32,000 INFO TaskExecutor {TERMINAL}
"""

print("=" * 74)
print("orchestrator.verdict 回归探针（ok-nte 日志判据）")
print("=" * 74)

print("\n[正向] 两种汇总格式都必须完整解析出三段")
for label, text in (("新格式 info_set", NEW_FMT), ("老格式 success:", OLD_FMT)):
    s, f, k = V.parse_nte_summary(text)
    print(f"\n  --- {label} ---")
    check("success = 3 项", s == ["甲", "乙", "丙"], f"实际 {s}")
    check("failed = []", f == [], f"实际 {f}")
    check("skipped 未丢失", k == ["丁"], f"实际 {k}")

print("\n[负向] 汇总行格式被破坏 ⇒ 三段全 None，不得返回部分数据")
BROKEN = ("DailyRoutineTask:WHATEVER success ['甲']\n"
          "DailyRoutineTask:WHATEVER failed ['乙']\n")
s, f, k = V.parse_nte_summary(BROKEN)
check("三段全 None", s is None and f is None and k is None, f"实际 {(s, f, k)}")

_, ev = V.nte_verdict(BROKEN + f"\n{DAILY_END}")
check("evidence 显式警示格式可能又变了",
      any("未解析到汇总行" in e for e in ev),
      " | ".join(ev)[:90])

print("\n[判定] 只看「是否完成」—— 单项失败不改变终态（用户要求）")
FAILED_RUN = f"""DailyRoutineTask:info_set success ['甲']
DailyRoutineTask:info_set failed ['乙', '丙']
DailyRoutineTask:info_set skipped []
DailyRoutineTask:任务失败: 乙
{TERMINAL}
"""
v, _ = V.nte_verdict(FAILED_RUN)
check("有终止标记 ⇒ SUCCESS（尽管有 2 项失败）", v == V.SUCCESS, f"实际 {v}")
check("但失败项必须能单独取出", V.nte_failures(FAILED_RUN) == ["乙", "丙"],
      f"实际 {V.nte_failures(FAILED_RUN)}")

print("\n[判定] 证据不足绝不报成功（INV-30）")
v, _ = V.nte_verdict("")
check("空文本 ⇒ UNKNOWN", v == V.UNKNOWN, f"实际 {v}")
v, _ = V.nte_verdict("完全无关的文字")
check("无关文字 ⇒ NO_TASK", v == V.NO_TASK, f"实际 {v}")
v, _ = V.nte_verdict("完全无关的文字", still_running=True)
check("无关文字 + 运行中 ⇒ RUNNING", v == V.RUNNING, f"实际 {v}")
PARTIAL = "DailyRoutineTask:任务完成: 甲\n"
v, _ = V.nte_verdict(PARTIAL)
check("只有单项完成、无终止标记 ⇒ 不报 SUCCESS", v != V.SUCCESS, f"实际 {v}")
v, _ = V.nte_verdict(PARTIAL, still_running=True)
check("同上 + 运行中 ⇒ RUNNING", v == V.RUNNING, f"实际 {v}")
v, _ = V.nte_verdict(DAILY_END)
check("「结束执行日常任务」单独出现 ⇒ SUCCESS", v == V.SUCCESS, f"实际 {v}")

print("\n[★ 假阳性] LogWindow 必须只认本次运行新增的日志")
# 造一个临时日志目录，模拟「上一次运行已成功，且**未被外部终止**」
import tempfile                                      # noqa: E402
tmp = Path(tempfile.mkdtemp(prefix="probe-verdict-"))
log = tmp / "ok-script.log"
log.write_text(OLD_FMT, encoding="utf-8")            # 历史：上一次成功

w = V.LogWindow(logdir=tmp)
check("构造后窗口为空（基线已记）", w.text() == "", f"实际 {len(w.text())} 字节")
v, ev = w.verdict()
check("刚构造就判 ⇒ 不报 SUCCESS（不得借用历史）", v != V.SUCCESS, f"实际 {v}")

# 本次运行**被外部强制终止**：只写了一点点，没有 ok:quit app、没有终止标记
with log.open("a", encoding="utf-8") as f:
    f.write("2026-10-16 00:30:00,000 INFO TaskExecutor 开始执行日常任务\n")
w.poll()
v, ev = w.verdict(still_running=True)
check("本次仅开头、无终止标记 ⇒ 不报 SUCCESS", v != V.SUCCESS, f"实际 {v}")
check("新窗口看不到历史成功汇总",
      "success=" not in " ".join(ev), " | ".join(ev)[:80])

# 本次真完成
with log.open("a", encoding="utf-8") as f:
    f.write(f"2026-10-16 00:31:00,000 INFO TaskExecutor {TERMINAL}\n")
w.poll()
v, _ = w.verdict()
check("本次写入终止标记后 ⇒ SUCCESS", v == V.SUCCESS, f"实际 {v}")

print("\n[LogWindow] 文件被截断/轮转时不得漏读")
before = w.text()
log.write_text("2026-10-16 01:00:00,000 INFO TaskExecutor 新文件内容\n",
               encoding="utf-8")                     # 变小 ⇒ 整体重读
w.poll()
check("变小后整体重读（能看到新内容）",
      "新文件内容" in w.text(), f"追加 {len(w.text()) - len(before)} 字节")

print("\n[分派] verdict_for 只服务 ok-nte，用错必须报错")
v, _ = V.verdict_for(P.NTE, text=DAILY_END)
check("nte ⇒ 走日志判据", v == V.SUCCESS, f"实际 {v}")
try:
    V.verdict_for(P.WW, text=DAILY_END)
    check("ww ⇒ 必须抛 ValueError（不得静默走日志判据）", False, "没抛异常")
except ValueError:
    check("ww ⇒ 必须抛 ValueError（不得静默走日志判据）", True)

print("\n[真日志] 本机 ok-nte 日志回归")
if V.NTE_LOGDIR.is_dir():
    files = sorted(V.NTE_LOGDIR.glob("ok-script*.log"))
    verdicts = {}
    for p in files:
        t = p.read_text(encoding="utf-8", errors="replace")
        v, _ = V.nte_verdict(t)
        verdicts.setdefault(v, []).append(p.name)
    for v in sorted(verdicts):
        print(f"    {v:<9} {len(verdicts[v])} 个: {verdicts[v][:3]}")
    check("至少有一个日志判为 SUCCESS", V.SUCCESS in verdicts,
          f"分布 { {k: len(v) for k, v in verdicts.items()} }")
    check("无异常终态（都在已知集合内）",
          set(verdicts) <= {V.SUCCESS, V.RUNNING, V.NO_TASK, V.UNKNOWN},
          f"实际 {sorted(verdicts)}")
else:
    print(f"    (跳过：{V.NTE_LOGDIR} 不存在)")

# 清理临时目录
try:
    for c in tmp.iterdir():
        c.unlink()
    tmp.rmdir()
except OSError:
    pass

print("\n" + "=" * 74)
if FAILED:
    print(f"❌ {len(FAILED)} 项不符合预期：")
    for n in FAILED:
        print(f"   - {n}")
    sys.exit(1)
print("✅ 全部通过")
