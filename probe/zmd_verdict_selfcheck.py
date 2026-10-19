# -*- coding: utf-8 -*-
"""回归探针：MaaEnd（program key = "zmd"）运行判据 —— 用**真实历史切片**回放。

## 这个探针要证明什么

1. **判据对得上真日志**：MaaEnd 的完成信号是 stop_agent_impl，
   启动失败是 run_pretask finished with exit code: 1；
   两者在真日志里的**次序**决定判定（start 之后的 pretask 失败属于下一次尝试）。
2. **假成功被挡住**（INV-30）：MaaEnd 启动会清理日志
   （应用日志原文 Auto-cleared log files and debug artifacts on launch: 2），
   mxu-tauri.log 一旦被重写，**上一次**运行的 stop_agent_impl 会落进
   本次窗口 ⇒ 若只按字节偏移读，就会把它当成本次完成 ⇒ 假成功。
   ZmdLogWindow 靠**行时间戳基线**挡这一类；这里用「重写回放」验证它真挡住。
3. **读不到 ≠ 完成**：空文本必须 UNKNOWN（不是 RUNNING、更不是 SUCCESS）。

## 为什么用真日志切片

判据是正则 + 次序逻辑，而正则会被程序升级悄悄打死（FAULT #18）。
probe/fixtures/zmd_run_ok.txt 是 mxu-tauri.log 的**原文切片**（未改一字），
不是照着正则造的样本 —— 自己造的样本永远恰好匹配自己写的正则。
fixture 缺失时才从真实日志重建（见 _extract_from_live）。

## 不做什么

不联网、不启动 MaaEnd、不写工作区外的文件（临时回放文件写在
probe/fixtures/_tmp/ 下，跑完删除）。
"""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:                                    # 控制台若是 GBK，别让不可映射字符炸掉探针
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import verdict as v  # noqa: E402

FIXTURE = ROOT / "probe" / "fixtures" / "zmd_run_ok.txt"
TMPDIR = ROOT / "probe" / "fixtures" / "_tmp"
LIVE = v.ZMD_LOGDIR / v.ZMD_LOG_NAME

RX_START = re.compile(v.ZMD_START_MARK)
RX_STOP = re.compile(v.ZMD_STOP_MARK)
RX_FAIL = re.compile(v.ZMD_PRETASK_FAIL)

FAILS = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (f" --- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def note(msg):
    print(f"  [NOTE] {msg}")


def _extract_from_live():
    """从真实 mxu-tauri.log 切出三段原文（fixture 缺失时才用）。

    · partial      = 最后一次完整运行的 start_tasks 起 30 行（中途，无终止行）
    · full         = 同一次运行的 start_tasks .. stop_agent_impl（含两端）
    · pretask_fail = 最后一条 run_pretask finished with exit code: 1 及其上文 7 行
    """
    lines = LIVE.read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [i for i, l in enumerate(lines) if RX_START.search(l)]
    stops = [i for i, l in enumerate(lines) if RX_STOP.search(l)]
    fails = [i for i, l in enumerate(lines) if RX_FAIL.search(l)]
    if not starts or not fails:
        raise SystemExit(f"fixture 缺失且真实日志里也切不出样本：{LIVE}")
    start = starts[-1]
    stop = next((i for i in stops if i > start), None)
    if stop is None:
        raise SystemExit(f"最后一次运行没有终止行，切不出 full 段：{LIVE}")

    head = [
        "# ZmdLogWindow / zmd_verdict 回放 fixture —— MaaEnd（program key = zmd）真实历史切片",
        "# 来源：E:/TOOLS/ScriptsGames/zmd/debug/mxu-tauri.log（只读切片，未改一字；行首方括号内是原文时间戳）",
        "# 段落格式：以 ### <名字> 开头的行是段标题，其余是日志原文（一条一行）",
        "# 为什么留这份原文：判据的正则、次序（start 先于 pretask 失败）都只能对着真日志定，",
        "# 不能靠记忆重造 —— 造出来的样本永远恰好匹配写出来的正则（自证循环）。",
    ]
    body = (head + ["### partial"] + lines[start:start + 30]
            + ["### full"] + lines[start:stop + 1]
            + ["### pretask_fail"] + lines[fails[-1] - 7:fails[-1] + 1])
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text("\n".join(body) + "\n", encoding="utf-8")
    note(f"fixture 缺失，已从真实日志重建：{FIXTURE}")


def _segments(text):
    """把 fixture 解析成 {段名: 原文}。"""
    segs, cur = {}, None
    for line in text.splitlines():
        if line.startswith("### "):
            cur = line[4:].strip()
            segs[cur] = []
        elif line.startswith("#"):
            continue
        elif cur is not None:
            segs[cur].append(line)
    return {k: "\n".join(x) for k, x in segs.items()}


# ============================================================================
print("\n--- 0. fixture（真实历史切片）---")
if not FIXTURE.exists():
    _extract_from_live()
segs = _segments(FIXTURE.read_text(encoding="utf-8"))
for need in ("partial", "full", "pretask_fail"):
    check(f"fixture 含 {need} 段", need in segs, f"段={sorted(segs)}")
if FAILS:
    print("fixture 不可用，后续断言无意义")
    sys.exit(1)

partial, full, fail_seg = segs["partial"], segs["full"], segs["pretask_fail"]

# 先确认切片本身的性质（否则后面的判定「通过」没有意义）
check("partial 段里有 start_tasks", RX_START.search(partial) is not None)
check("partial 段里**没有**终止行（切在运行中途）", RX_STOP.search(partial) is None)
check("full 段里 start 与 stop 各有且仅有 1 条",
      len(v._zmd_hits(full, v.ZMD_START_MARK)) == 1
      and len(v._zmd_hits(full, v.ZMD_STOP_MARK)) == 1)
check("full 段里**没有** pretask 失败（第 4 次运行的窗口是干净的）",
      not v._zmd_hits(full, v.ZMD_PRETASK_FAIL))
check("pretask_fail 段里有失败行、且**没有** start / stop",
      len(v._zmd_hits(fail_seg, v.ZMD_PRETASK_FAIL)) == 1
      and not v._zmd_hits(fail_seg, v.ZMD_START_MARK)
      and not v._zmd_hits(fail_seg, v.ZMD_STOP_MARK))

# ============================================================================
print("\n--- 1. 判据回放（真实切片）---")
ver, ev = v.zmd_verdict(partial)
check("中途切片 => RUNNING", ver == v.RUNNING, ver)
check("  且证据说明「尚无终止信号」", any("尚无终止信号" in e for e in ev), ev[:1])

ver, ev = v.zmd_verdict(full)
check("完整切片 => SUCCESS", ver == v.SUCCESS, ver)
check("  证据含 start 原文", any(e.startswith("[start]") for e in ev))
check("  证据含 stop 原文", any(e.startswith("[stop]") for e in ev))
check("  证据含 killproc 原文（本次配置勾了结束后关游戏）",
      any(e.startswith("[killproc]") for e in ev), [e[:40] for e in ev])
check("  每类证据不超过 2 条",
      all(sum(1 for e in ev if e.startswith("[" + k + "]")) <= 2
          for k in ("start", "stop", "killproc", "pretask_fail")), len(ev))
check("  证据已去 ANSI 颜色码（ESC 不得漏进证据）",
      all(chr(27) not in e for e in ev))

ver, ev = v.zmd_verdict(fail_seg)
check("启动失败切片 => FAILED", ver == v.FAILED, ver)
check("  证据含 pretask 失败原文",
      any(e.startswith("[pretask_fail]") for e in ev), [e[:60] for e in ev])
check("  证据含 agent 侧报错原文（已去 ANSI）",
      any(e.startswith("[agent]") for e in ev), [e[:60] for e in ev])

check("空文本 => UNKNOWN", v.zmd_verdict("")[0] == v.UNKNOWN)
check("纯空白 => UNKNOWN", v.zmd_verdict("  \n\t\n")[0] == v.UNKNOWN)
check("空文本与 RUNNING 不同（读不到 ≠ 还在跑）", v.zmd_verdict("")[0] != v.RUNNING)

# 次序规则：start 之后的 pretask 失败属于下一次尝试，本次仍按 stop 判
ver, ev = v.zmd_verdict(fail_seg + "\n" + full)
check("「pretask 失败在 start 之前」的合并窗口 => SUCCESS（不是 FAILED）",
      ver == v.SUCCESS, ver)
stop_only = next(ln for ln in full.splitlines() if RX_STOP.search(ln))
ver, ev = v.zmd_verdict(fail_seg + "\n" + stop_only)
check("有 pretask 失败、无 start、但出现 stop 行 => FAILED", ver == v.FAILED, ver)

# ============================================================================
print("\n--- 2. 时间戳第二道闸（假成功防线，INV-30）---")
base = datetime(2026, 10, 17, 23, 43, 57)

old_stop = ("[2026-10-17][23:00:00][INFO][mxu_lib::commands::maa_agent] "
            "stop_agent_impl called for instance: OLDINSTANCE")
old_other = ("[2026-10-17][23:00:05][DEBUG][mxu_lib::commands::state] "
             "maa_get_all_states called")
new_start = ("[2026-10-17][23:43:58][DEBUG][mxu_lib::commands::maa_agent] "
             "[start_tasks] All tasks submitted, total: 12 task_ids")
new_stop = ("[2026-10-17][23:58:26][INFO][mxu_lib::commands::maa_agent] "
            "stop_agent_impl called for instance: yj2gs5w")

got = v.zmd_filter_since(old_stop + "\n" + old_other + "\n" + new_start, base)
check("早于基线的 stop 行被丢弃", "OLDINSTANCE" not in got, got[:60])
check("基线之后的 start 行被保留", "start_tasks" in got)

got = v.zmd_filter_since(old_stop, None)
check("基线为 None 时不过滤（降级路径不吞内容）", "OLDINSTANCE" in got)

got = v.zmd_filter_since(
    "[2026-10-17][23:00:00][INFO][x] a\n     续行\n"
    "[2026-10-18][00:00:01][INFO][x] b", base)
check("无时间戳的续行沿用上一行时间戳（早于基线 => 一起丢弃）",
      "续行" not in got and "b" in got, got.replace("\n", " | ")[:80])

# --- 2b. 窗口级回放：文件被清空重写后，旧 stop 不得变成完成信号 --------
print("\n--- 2b. ZmdLogWindow 重写回放 ---")
TMPDIR.mkdir(parents=True, exist_ok=True)
tmp = TMPDIR / "mxu-tauri.log"
try:
    pad = "\n".join(f"[2026-10-17][23:00:0{i}][DEBUG][x] 历史填充行 {i}"
                    for i in range(9))
    tmp.write_text(old_stop + "\n" + pad + "\n" + old_other + "\n", encoding="utf-8")
    w = v.ZmdLogWindow(path=tmp)
    check("窗口基线 = 文件最后一行的时间戳",
          w._baseline == datetime(2026, 10, 17, 23, 0, 5), w._baseline)
    check("刚 mark() 后 poll() 为空（没有新增）", w.poll() == "" and w.text() == "")

    # MaaEnd 启动清理日志：文件被重写成更短的内容（上一次的 stop 仍在里面）
    tmp.write_text(old_stop + "\n" + new_start + "\n", encoding="utf-8")
    got = w.poll()
    check("文件变小 => 整段重读，但旧 stop 被时间戳闸挡掉",
          "OLDINSTANCE" not in got and "start_tasks" in got,
          got.replace("\n", " | ")[:100])
    check("  此时判据只能是 RUNNING（拿到的是本次 start）",
          w.verdict()[0] == v.RUNNING, w.verdict()[1][:1])
    check("  若不设时间戳闸，这段文本会被判 SUCCESS —— 正是不许发生的事",
          v.zmd_verdict(old_stop + "\n" + new_start)[0] == v.SUCCESS)

    # 追加一条**时间戳更早**的 stop（基线之后才被读到）⇒ 必须丢弃
    with tmp.open("a", encoding="utf-8") as f:
        f.write("[2026-10-17][23:00:02][INFO][mxu_lib::commands::maa_agent] "
                "stop_agent_impl called for instance: LATE_OLD\n")
    got = w.poll()
    check("基线之后读到的、时间戳更早的 stop 行被丢弃",
          "LATE_OLD" not in got, got[:80])
    check("  窗口文本里不含任何早于基线的 stop", "LATE_OLD" not in w.text())
    check("  判定仍是 RUNNING", w.verdict()[0] == v.RUNNING)
    check("  缓冲区被重建而不是追加（start 只出现 1 次，不重复计数）",
          len(v._zmd_hits(w.text(), v.ZMD_START_MARK)) == 1,
          len(v._zmd_hits(w.text(), v.ZMD_START_MARK)))

    # 本次真正的收尾：追加（时间戳更晚）⇒ 必须认
    with tmp.open("a", encoding="utf-8") as f:
        f.write(new_stop + "\n")
    w.poll()
    ver, ev = w.verdict()
    check("本次 stop 追加后 => SUCCESS", ver == v.SUCCESS, ver)
    check("  证据含本次 stop 的实例号 yj2gs5w",
          any("yj2gs5w" in e for e in ev), [e[:60] for e in ev])
    check("  证据**不含**上一次的实例号 OLDINSTANCE",
          all("OLDINSTANCE" not in e for e in ev))
finally:
    shutil.rmtree(TMPDIR, ignore_errors=True)

# ============================================================================
print("\n--- 3. 真实文件上的窗口 ---")
w0 = v.ZmdLogWindow()
check("默认路径 = <zmd>/debug/mxu-tauri.log",
      w0.path.name == "mxu-tauri.log" and "zmd" in str(w0.path).lower(), str(w0.path))
if LIVE.exists():
    chunk = w0.poll()
    if chunk == "":
        check("真实文件上 mark() 后 poll() 立即为空（MaaEnd 当前空闲）", w0.text() == "")
    else:
        # MaaEnd 恰好在写日志：退而验「不变式」而不是「空」
        bad = [ln for ln in chunk.splitlines()
               if (v.zmd_parse_ts(ln) and w0._baseline
                   and v.zmd_parse_ts(ln) < w0._baseline)]
        check("真实文件此刻在增长，改验不变式：没有早于基线的行", not bad,
              f"基线={w0._baseline}")
    check("基线非空（真实文件末尾有时间戳）", w0._baseline is not None, w0._baseline)
else:
    note(f"真实日志不存在（从未跑过任务？）：{LIVE}")

# ============================================================================
print("\n--- 4. 自检函数（读不到 / 认不出）---")
probs = v.zmd_log_self_check()
# MaaEnd 每次启动都会重建 mxu-tauri.log ⇒ 「当前实例还没跑过任何任务」时，
# 认不出 start/stop 是**预期**的（函数自己的措辞就是这么说的），不能算失败。
_live_txt = LIVE.read_text(encoding="utf-8", errors="replace") if LIVE.exists() else ""
_pristine = ("start_tasks" not in _live_txt) and ("stop_agent_impl" not in _live_txt)
if _pristine:
    note("当前实例的 mxu-tauri.log 里没有任何任务痕迹（从未跑过任务）"
         "⇒ 只要求问题全部属于「认不出、从未跑过任务时属正常」这一类")
    check("真实环境 / 干净实例 => 只允许「认不出」两类问题",
          all("从未跑过任务" in p for p in probs), probs)
else:
    check("真实环境下 zmd_log_self_check() 无问题", probs == [], probs)
missing = v.zmd_log_self_check(TMPDIR / "nope.log")
check("文件不存在 => 1 条问题，且说明「从未跑过任务时属正常」",
      len(missing) == 1 and "从未跑过任务" in missing[0], missing)

TMPDIR.mkdir(parents=True, exist_ok=True)
wrongfmt = TMPDIR / "wrong.log"
wrongfmt.write_text("[2026-10-17][23:00:00][INFO][x] MaaEnd 升级改了措辞\n",
                    encoding="utf-8")
probs = v.zmd_log_self_check(wrongfmt)
check("措辞认不出 => 同时报「认不出 start」与「认不出 stop」", len(probs) == 2,
      [p[:40] for p in probs])
shutil.rmtree(TMPDIR, ignore_errors=True)

# ============================================================================
print("\n--- 5. 回归：ok-ww / ok-nte 的判据未被 zmd 改动影响 ---")
probs = v.logdir_self_check()
check("logdir_self_check() 不再对 MaaEnd 报「没有 ok-script*.log」的假问题",
      probs == [], probs)
lw = v.LogWindow()
check("LogWindow 默认目录仍是 ok-nte 的 logs（行为不变）",
      str(lw.logdir).lower() == str(Path(v.NTE_LOGDIR)).lower(), str(lw.logdir))
ver, _ = v.nte_verdict("TaskExecutor:Successfully Executed Task, Exiting Game and App!")
check("nte_verdict 仍认原终止标记", ver == v.SUCCESS, ver)
# 分派已由别人接线（2026-10-18 22:10）：verdict_for('zmd') 走 zmd_verdict，
# 且 log_window 分支只认一参协议，误传 LogWindow 会 TypeError 而不是静默假成功。
ver, _ = v.verdict_for("zmd", text=full)
check("verdict_for('zmd', text=完整段) 分派到 zmd_verdict => SUCCESS",
      ver == v.SUCCESS, ver)
ver, _ = v.verdict_for("zmd", text=partial)
check("verdict_for('zmd', text=中途段) => RUNNING", ver == v.RUNNING, ver)

# ============================================================================
print()
if FAILS:
    print(f"FAILED: {len(FAILS)} 项未通过 -> {FAILS}")
    sys.exit(1)
print("ALL PASSED —— MaaEnd 判据可用：真实切片判得对、时间戳闸挡得住假成功、读不到报 UNKNOWN。")
