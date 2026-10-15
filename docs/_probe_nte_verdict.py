"""_probe_nte_verdict.py — ok-nte 判据的回归探针（FAULT #18）

**为什么要这个探针**：FAULT #18 的失效是**静默的** ——
ok-nte 升级后把汇总行从「一行三段」改成「三行独立 `info_set`」，
老正则 `DailyRoutineTask:success:` 变成**匹配不到**，
于是 `success`/`skipped` 悄悄变成 `None`、`failed` 悄悄变成 `[]`。
**不报错、不抛异常，只是数据少了一半**。
在它被肉眼发现之前，任何「跑通了没报错」的结论都是不可信的。

本探针因此**双向**验证：
  - 正向：两种真实格式都必须**完整**解析出三段（含被跳过的任务）
  - 负向：格式被破坏时必须**明确说不认识**，而**不得**静默返回部分数据

不依赖 ok-nte 正在运行，也不需要提权 —— 纯文本解析，随时可跑。

    python -X utf8 docs/_probe_nte_verdict.py
"""

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "probe"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import nte_verdict as V          # noqa: E402

FAILED = []

# 「这个日志真的跑过日常任务」的判据：必须有**执行痕迹**，
# 而不是文件里出现过 DailyRoutineTask 这个词（配置转储里必然出现）。
DAILY_RUN = re.compile(
    r"DailyRoutineTask:(?:开始|info_set|结束)|结束执行日常任务|开始执行日常任务")


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


# --- 合成样本：两种真实格式，内容等价 ----------------------------------------
NEW_FMT = """2026-10-15 00:23:15,566 INFO TaskExecutor DailyRoutineTask:info_set success ['甲', '乙', '丙']
2026-10-15 00:23:15,566 INFO TaskExecutor DailyRoutineTask:info_set failed []
2026-10-15 00:23:15,566 INFO TaskExecutor DailyRoutineTask:info_set skipped ['丁']
2026-10-15 00:23:15,567 INFO TaskExecutor DailyRoutineTask:结束执行日常任务
2026-10-15 00:23:15,570 INFO TaskExecutor TaskExecutor:Successfully Executed Task, Exiting Game and App!
"""

OLD_FMT = """2026-10-08 23:15:31,774 INFO TaskExecutor DailyRoutineTask:success: ['甲', '乙', '丙']
failed: []
skipped: ['丁']
2026-10-08 23:15:31,775 INFO TaskExecutor DailyRoutineTask:结束执行日常任务
2026-10-08 23:15:31,776 INFO TaskExecutor TaskExecutor:Successfully Executed Task, Exiting Game and App!
"""

# 旧格式会**额外**伴随一条 info_set 行（过渡期实测如此），此处模拟真实情形
OLD_FMT_REAL = OLD_FMT.replace(
    "2026-10-08 23:15:31,774 INFO TaskExecutor DailyRoutineTask:success:",
    "2026-10-08 23:15:31,774 INFO TaskExecutor DailyRoutineTask:info_set success ['甲', '乙', '丙']\n"
    "2026-10-08 23:15:31,774 INFO TaskExecutor DailyRoutineTask:success:")

print("=" * 74)
print("ok-nte 判据回归探针（FAULT #18：汇总行格式漂移）")
print("=" * 74)

print("\n[正向] 两种格式都必须完整解析出三段")
for label, text in (("新格式 info_set（v1.4.8+）", NEW_FMT),
                    ("老格式 success:（≤ v1.4.7）", OLD_FMT),
                    ("过渡期（两种都在）", OLD_FMT_REAL)):
    s, f, k = V.parse_summary(text)
    print(f"\n  --- {label} ---")
    check("success 解析出 3 项", s == ["甲", "乙", "丙"], f"实际 {s}")
    check("failed 解析出空表", f == [], f"实际 {f}")
    # 这一条是 FAULT #18 的核心：被跳过的任务曾**静默消失**
    check("skipped 未丢失（'丁'）", k == ["丁"], f"实际 {k}")

print("\n[负向] 格式被破坏时必须明说『不认识』，不得静默返回部分数据")
BROKEN = """2026-10-15 00:23:15,566 INFO TaskExecutor DailyRoutineTask:SUMMARY_BROKEN success ['甲']
2026-10-15 00:23:15,566 INFO TaskExecutor DailyRoutineTask:SUMMARY_BROKEN failed ['乙']
"""
s, f, k = V.parse_summary(BROKEN)
check("三段全为 None（不返回部分数据）",
      s is None and f is None and k is None, f"实际 {(s, f, k)}")

_, ev = V.verdict_from_log(BROKEN, latest_only=False)
joined = " | ".join(ev)
check("evidence 里显式警示『未解析到汇总行』",
      "未解析到汇总行" in joined, joined[:100])

print("\n[负向] 空文本不得被判成成功")
v, _ = V.verdict_from_log("", latest_only=False)
check("空文本 => UNKNOWN", v == "UNKNOWN", f"实际 {v}")

v, _ = V.verdict_from_log("随便一些无关的文字", latest_only=False)
check("无任务痕迹 => NO_TASK", v == "NO_TASK", f"实际 {v}")

print("\n[正向] 真日志回归（若本机存在 ok-nte 日志）")
if V.LOGDIR.is_dir():
    files = sorted(V.LOGDIR.glob("ok-script*.log"))
    print(f"  找到 {len(files)} 个日志文件")
    parsed_new = parsed_old = 0
    for p in files:
        t = V.read(p)
        s, f, k = V.parse_summary(t)
        if s is not None or f is not None or k is not None:
            parsed_new += 1
        elif DAILY_RUN.search(t):
            # ⚠️ 判据必须是「真的跑过日常任务」，不是「文件里出现过
            # DailyRoutineTask 这个词」。该词在**配置转储**里必然出现
            # （L1 的 onetime_tasks 清单含 'src.tasks.daily.DailyRoutineTask'），
            # 所以旧写法对每个日志都成立 —— 实测 10-14 那个日志是一整晚的
            # DSDFarmTask（九百九十九夜），根本没有日常汇总行，
            # 却被这行告警误导成「格式又变了」。
            # 这正是 FAULT #18/#20/#27 的同型错误：单看一个信号就下结论。
            print(f"    [!] {p.name} 跑过日常任务但汇总行未解析到 —— 格式可能又变了")
        else:
            print(f"    -  {p.name} 非日常任务运行（无日常任务痕迹），跳过")
    check("至少有一个日志能解析出汇总", parsed_new > 0, f"{parsed_new} 个")
else:
    print(f"  (跳过：{V.LOGDIR} 不存在)")

print("\n" + "=" * 74)
if FAILED:
    print(f"❌ {len(FAILED)} 项不符合预期：")
    for n in FAILED:
        print(f"   - {n}")
    sys.exit(1)
print("✅ 全部通过")
