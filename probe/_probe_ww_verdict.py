"""回归探针：ok-ww 也能用日志判据判定终态（FAULT #15）。

## 这个探针要证明什么

长期记录的说法是：ok-ww 的终态依据是**画面**（完成帧 `exit_notice`），
而那张图**从未采集** ⇒ 「无法判定正常完成，只能以超时收场」，
被列为本项目「唯一的功能缺口」。

**实测推翻了这个前提。** ok-ww 与 ok-nte 是同一套 ok-script 运行时，
收尾写的是**逐字相同**的一句话：

    TaskExecutor:Successfully Executed Task, Exiting Game and App!

逐文件统计：ok-ww 凡**跑到完成**的那几次，终止标记与「杀游戏」各出现 1 次；
没跑完的文件两者皆 0。⇒ 这是**两程序共用**的终止标记。

## 为什么必须用真实日志做回归

判据是**正则**，而正则会被程序升级悄悄打死（FAULT #18 的教训：
ok-nte v1.4.8 改了汇总格式，老正则静默失效，把 5 项失败报成 0 项）。
所以这里既测合成用例（边界），也测**全部历史真实日志**（防漂移）。

## 分层

- **正向**：真实「已跑完」的日志必须判 SUCCESS；
- **负向**：没跑完的日志必须**不得**判 SUCCESS（证据不足报 UNKNOWN）；
- **静态**：`verdict_for(WW)` 必须真的走日志判据，而不是抛 ValueError；
- **路径**：两个程序的日志目录都必须真实存在（否则静默读空）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import verdict as v, programs  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


TERM_LINE = ("2026-10-15 20:37:29,624 INFO TaskExecutor "
             "TaskExecutor:Successfully Executed Task, Exiting Game and App!")
END_LINE = "2026-10-15 20:37:29,623 INFO TaskExecutor DailyTask:Daily Task Completed"
KILL_LINE = ("2026-10-15 20:37:34,631 INFO TaskExecutor process:Trying to kill the exe "
             "{'name': 'Client-Win64-Shipping.exe', 'pid': 1}")
PHASE_LINE = ("2026-10-15 20:37:27,062 INFO TaskExecutor MergeEchoTask:"
              "info_set current task wait main esc=True")

print("=" * 70)
print("探针：ok-ww 日志判据（FAULT #15）")
print("=" * 70)

# ---------------- 1. 合成用例 ----------------
print("\n--- 合成用例 ---")
full = "\n".join([PHASE_LINE, END_LINE, TERM_LINE, KILL_LINE])
ver, ev = v.ww_verdict(full)
print(f"  完整收尾 -> {ver}")
print(f"    {ev[0]}")
check("✓ 完整收尾判 SUCCESS", ver == v.SUCCESS)
check("✓ 证据里标出杀游戏=True", "杀游戏=True" in ev[0])

ver, _ = v.ww_verdict("\n".join([PHASE_LINE, END_LINE]))
check("✓ 只有「日常结束」也判 SUCCESS", ver == v.SUCCESS)

ver, _ = v.ww_verdict(PHASE_LINE, still_running=True)
check("✓ 只有阶段行 + 在跑 ⇒ RUNNING", ver == v.RUNNING)

ver, _ = v.ww_verdict(PHASE_LINE, still_running=False)
check("✓ 只有阶段行 + 没跑 ⇒ UNKNOWN（不臆断成功）", ver == v.UNKNOWN,
      "证据不足绝不报成功（INV-30）")

ver, _ = v.ww_verdict("", still_running=True)
check("✓ 空日志 + 在跑 ⇒ RUNNING", ver == v.RUNNING,
      "刚点击时日志为空是正常的")

ver, _ = v.ww_verdict("", still_running=False)
check("✓ 空日志 + 没跑 ⇒ UNKNOWN", ver == v.UNKNOWN)

ver, _ = v.ww_verdict("无关的一行文字")
check("✓ 无关文字 ⇒ NO_TASK", ver == v.NO_TASK)

# ⚠️ ok-ww 没有 ok-nte 那种逐项汇总，证据里**不该**出现「未解析到汇总行」
#    的假警报（照抄 ok-nte 正则会天天误报）。
_, ev2 = v.ww_verdict(full)
check("✓ 不误报「未解析到汇总行」（ok-ww 本就没有汇总）",
      not any("未解析到汇总" in e for e in ev2))

# ---------------- 2. 真实日志回归 ----------------
print("\n--- 真实日志（ok-ww 全部历史）---")
ld = v._logdir_for(programs.WW)
logs = sorted(ld.glob("ok-script*.log"))
if not logs:
    check("找到 ok-ww 真实日志", False, f"{ld} 下没有 ok-script*.log")
else:
    n_succ = n_unk = 0
    for f in logs:
        t = f.read_text(encoding="utf-8", errors="replace")
        ver, ev = v.ww_verdict(t)
        print(f"  {f.name:30} -> {ver:8} {ev[0]}")
        if ver == v.SUCCESS:
            n_succ += 1
        elif ver == v.UNKNOWN:
            n_unk += 1
    check("✓ 至少有一个历史日志判 SUCCESS（判据确实能认出来）", n_succ > 0,
          f"SUCCESS={n_succ} UNKNOWN={n_unk}")
    # 交叉验证：判 SUCCESS 的文件必须真的含终止标记或日常结束
    bad = []
    for f in logs:
        t = f.read_text(encoding="utf-8", errors="replace")
        ver, _ = v.ww_verdict(t)
        has_mark = ("Successfully Executed Task, Exiting Game and App!" in t
                    or "DailyTask:Daily Task Completed" in t)
        if ver == v.SUCCESS and not has_mark:
            bad.append(f.name)
    check("✓ 判 SUCCESS 的都有实据（无凭空成功）", not bad, f"可疑: {bad}")

# ---------------- 3. 分派与路径 ----------------
print("\n--- 分派与路径 ---")
ver, ev = v.verdict_for(programs.WW, text=full)
check("✓ verdict_for(WW) 不再抛错，且走日志判据", ver == v.SUCCESS)

ver, ev = v.verdict_for(programs.NTE, text=full)
check("✓ verdict_for(NTE) 仍可用", ver == v.SUCCESS)

try:
    v.verdict_for("不存在的程序", text=full)
    check("✓ 未知程序必须抛错（不回落默认）", False, "居然没抛")
except (KeyError, ValueError):
    check("✓ 未知程序必须抛错（不回落默认）", True)

probs = v.logdir_self_check()
check("✓ 两个程序的日志目录都真实存在且非空", not probs, f"问题: {probs}")

# 关键：目录名必须带 ok- 前缀（初版写错成 <key>，静默读空）
for p in programs.ALL:
    d = str(v._logdir_for(p)).lower()
    check(f"✓ {p.key} 日志目录名带 ok- 前缀", f"apps\\ok-{p.key}\\" in d, d)

# ---------------- 4. LogWindow 按程序选目录 ----------------
print("\n--- LogWindow ---")
w = v.LogWindow(program=programs.WW)
check("✓ LogWindow(program=WW) 指向 ok-ww 的目录",
      "ok-ww" in str(w.logdir), str(w.logdir))
w2 = v.LogWindow(program=programs.NTE)
check("✓ LogWindow(program=NTE) 指向 ok-nte 的目录",
      "ok-nte" in str(w2.logdir), str(w2.logdir))
check("✓ 新窗口初始为空（只看本次运行）",
      w.text() == "" and w.verdict(still_running=True)[0] == v.RUNNING)

print("\n" + "=" * 70)
if FAILS:
    print(f"FAILED：{len(FAILS)} 项未通过")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("全部通过")
