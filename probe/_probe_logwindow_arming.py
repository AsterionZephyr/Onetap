# -*- coding: utf-8 -*-
"""FAULT #25 回归探针 —— LogWindow 必须在**点击之前**武装。

背景（实测踩到，非假想）：

`step8_run_task.wait_for_nte_completion` 原来在**函数内部**构造
`verdict_mod.LogWindow()`，而这个函数是在 `click_and_confirm` **之后**才被调用。
`LogWindow.__init__` 会记录各日志文件的当前字节大小作基线 ⇒ 基线取在**点击之后**
⇒ 点击到构造之间 ok-nte 写的日志**全部读不到**。

实测：ok-nte 点「开始」后 1 秒内就写了大量启动日志，此时才构造 LogWindow，
`text()` 恒为 0、verdict 恒 `unknown` ⇒ **整条 ok-nte 链永远等不到完成**，
而且**不报任何错**（静默）。

本探针用**临时日志目录**复现「先写日志、后武装」与「先武装、后写日志」
两种顺序的差异，不依赖 ok-nte 的实时状态，因此可重复。

用法：D:\\WORKs\\Anaconda\\python.exe -X utf8 probe\\_probe_logwindow_arming.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import verdict  # noqa: E402

TERMINAL = ("2026-10-16 02:04:00,000 INFO TaskExecutor "
            "TaskExecutor:Successfully Executed Task, Exiting Game and App!")

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print(f"  {'[PASS]' if ok else '[FAIL]'} {name}")
    print(f"         实际={got!r} 期望={want!r}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lw-arm-"))
    logfile = tmp / "ok-script.log"

    print("=" * 72)
    print("FAULT #25 —— LogWindow 武装时机")
    print("=" * 72)

    # ---- 场景 A：错误顺序 —— 先写日志，后武装（复现 bug）------------------
    print("\n[场景 A] 错误顺序：先写日志 → 后构造 LogWindow（复现 bug）")
    logfile.write_text(TERMINAL + "\n", encoding="utf-8")
    lw_late = verdict.LogWindow(logdir=tmp)
    lw_late.poll()
    late_text_len = len(lw_late.text())
    late_v, late_ev = lw_late.verdict(still_running=False)
    print(f"         text 长度 = {late_text_len}，verdict = {late_v}")
    check("先写后武装 ⇒ 读不到任何内容", late_text_len, 0)
    check("先写后武装 ⇒ verdict 为 unknown（等不到完成）",
          late_v, verdict.UNKNOWN)

    # ---- 场景 B：正确顺序 —— 先武装，后写日志（修复后）-------------------
    print("\n[场景 B] 正确顺序：先构造 LogWindow（mark）→ 再写日志")
    logfile.write_text("", encoding="utf-8")          # 清空，模拟新一轮
    lw_early = verdict.LogWindow(logdir=tmp)          # ★ 点击前武装
    with open(logfile, "a", encoding="utf-8") as f:   # ★ 点击后 ok-nte 写日志
        f.write("2026-10-16 02:03:50 IR TaskExecutor LauncherTask:start\n")
        f.write(TERMINAL + "\n")
    lw_early.poll()
    early_text = lw_early.text()
    early_v, early_ev = lw_early.verdict(still_running=False)
    print(f"         text 长度 = {len(early_text)}，verdict = {early_v}")
    for e in early_ev:
        print(f"           {e}")
    check("先武装后写 ⇒ 读到内容", len(early_text) > 0, True)
    check("先武装后写 ⇒ verdict 为 success", early_v, verdict.SUCCESS)

    # ---- 场景 C：增量语义 —— 第二次 poll 只拿新增 ------------------------
    print("\n[场景 C] 增量：poll 之间新增的内容必须被累积")
    with open(logfile, "a", encoding="utf-8") as f:
        f.write("2026-10-16 02:05:00 IR TaskExecutor DailyRoutineTask:结束执行日常任务\n")
    lw_early.poll()
    check("新增行被累积", "结束执行日常任务" in lw_early.text(), True)

    # ---- 场景 D：文件被截断（日志轮转）必须整体重读，不能只读差值 -------
    print("\n[场景 D] 日志被截断/轮转 ⇒ 必须整体重读")
    # ⚠️ 必须让新内容与基线**字节数不同**，否则 size == prev 会（正确地）
    #    走「无变化」分支 —— 那是探针写错了，不是产品缺陷（本探针初版即犯此错）。
    logfile.write_text("A" * 500 + "\n", encoding="utf-8")   # 大：501 字节
    lw_trunc = verdict.LogWindow(logdir=tmp)                 # 基线 = 501
    logfile.write_text(TERMINAL + "\n", encoding="utf-8")    # 小：160 字节（真的变小）
    lw_trunc.poll()
    print(f"         基线 501 → 现 {logfile.stat().st_size} 字节，"
          f"读得 {len(lw_trunc.text())} 字符")
    check("截断到更小后仍能读到内容", len(lw_trunc.text()) > 0, True)
    check("读到的是截断后的新内容",
          "Successfully Executed Task" in lw_trunc.text(), True)

    # ---- 场景 E：文件新出现（真轮转产物）必须整体读 ---------------------
    print("\n[场景 E] 轮转：武装后出现新文件 ⇒ 必须整体读")
    lw_new = verdict.LogWindow(logdir=tmp)
    (tmp / "ok-script.2026-10-17.log").write_text(TERMINAL + "\n", encoding="utf-8")
    lw_new.poll()
    check("新出现的日志文件被整体读入",
          TERMINAL[:40] in lw_new.text(), True)

    # ---- 场景 F：向后兼容 —— logdir 缺省应指向 ok-nte ----------------
    print("\n[场景 F] 兼容性：缺省 logdir 指向 ok-nte")
    lw_def = verdict.LogWindow()
    check("缺省 logdir == NTE_LOGDIR", lw_def.logdir, verdict.NTE_LOGDIR)

    # 清理
    for p in tmp.glob("*"):
        p.unlink()
    tmp.rmdir()

    print()
    print("=" * 72)
    n_ok = sum(RESULTS)
    print(f"总判定：{'✅ 全部通过' if n_ok == len(RESULTS) else '❌ 有失败'} "
          f"({n_ok}/{len(RESULTS)})")
    print("=" * 72)
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
