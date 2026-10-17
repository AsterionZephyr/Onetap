"""整轮时间上限（RUN_TIMEOUT）超时收尾验证 —— 用户裁定「半小时到点关窗口关游戏」。

跑法（在仓库根，**需要管理员**）：
    python -X utf8 probe/_probe_run_timeout.py            # 全部
    python -X utf8 probe/_probe_run_timeout.py --static   # 只做静态检查（不需提权）

## 这条路径为什么必须单独验

`main.py` 的整轮上限是**无人值守的最后一道保险**：跑了 30 分钟还没完就强制收尾。
它从没在真实运行里触发过（历史各次都在 12 分钟内正常完成），所以「到点真的会
关窗口关游戏吗」一直是纸面结论。

## 关键发现：验证它**不需要改源码**

`--run-timeout` 本来就是命令行参数（`orchestrator/steps/main.py:132`，
`type=float, default=RUN_TIMEOUT`）。想验超时就直接传个小值，例如
`--run-timeout 30`，跑完不用改回来。改 `RUN_TIMEOUT` 常量再改回去是多余动作，
而且多一次「忘了改回来」的风险。

## 超时检查的粒度

`main.py:224` 在**每节开始之前**查一次 `deadline.expired()`，所以触发点是
「某节跑完之后、下一节开始之前」。节点 4/5 各自要等几十秒，因此把小上限
（30s）设上去，能可靠地在节点 4 返回后触发。

## ⚠️ 实测记录（2026-10-17，run-timeout-test-20261017-114844）

`--run-timeout 30` 的实测结果：

    [主控] 整轮时间上限到了（已用 40s / 上限 30s（余 0s））—— 执行超时收尾
    [超时收尾] ok-nte —— 整轮时间上限到了（run-timeout）
      关闭 ok-nte 窗口 hwnd=4194676 标题='ok-nte'
      游戏无窗口可关            ← 30s 时游戏还没被拉起
      ok-nte 进程已全部退出
      游戏进程已全部退出

`state.json` 落盘正确：`result="timeout"`、
`result_detail="整轮超过 30s 上限，已强制收尾"`、
`watchdog.reason="run-timeout"`、`watchdog.target="nte"`、
`closed_windows=[4194676]`。

**但「关游戏」那一半没测到** —— 因为 30s 时 ok-nte 还没把游戏拉起来
（节点 2 只负责拉起第一层，只用 4.1s；游戏要几十秒才出现）。
⇒ 游戏侧另外单独验：手工拉起 `NTEGame.exe`，再调
`force_close(nte, reason='run-timeout', close_game=True)`，实测关掉了
**9 个**游戏窗口（`QTrayIconMessageWindow` / `NTEGame`×2 /
`__wglDummyWindowFodder` / `dac80dc7…`×2 / `MSCTFIME UI` / `Default IME`×2），
游戏进程归零，且 `killed_game=[]`（**体面退出**，WM_CLOSE 就够，无需强杀）。

⇒ **两点必须诚实说明**：完整链路是分两次取证的，不是同一次运行跑完的。
若要在**同一次**运行里覆盖游戏侧，得把上限设到 120s 左右，让超时发生在
节点 5/6/7（那时游戏已起来）。今天额度已用，那样做是安全的（ok-nte 会
立刻发现「今日已完成」直接收尾）。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

MAIN_PY = os.path.join(ROOT, "orchestrator", "steps", "main.py")
WATCHDOG_PY = os.path.join(ROOT, "orchestrator", "watchdog.py")

_fails = []
_checks = 0


def ck(ok, label, extra=""):
    global _checks
    _checks += 1
    print(f"  [{'OK ' if ok else 'NG '}] {label}" + (f"  {extra}" if extra else ""))
    if not ok:
        _fails.append(label)
    return ok


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- 静态检查
def static():
    print("\n[1] main.py —— 超时收尾的接线")
    src = read(MAIN_PY)

    ck("RUN_TIMEOUT = 1800.0" in src,
       "RUN_TIMEOUT 默认 1800.0（用户裁定：半小时）")

    m = re.search(r'"--run-timeout"[^)]*type=float[^)]*default=RUN_TIMEOUT', src, re.S)
    ck(bool(m), "--run-timeout 是**命令行参数**（可传小值验证，无需改源码）")

    ck("watchdog.Deadline(args.run_timeout, log=log)" in src,
       "用 watchdog.Deadline 计时")
    ck("deadline.begin()" in src, "计时起点明确（干活之前）")

    m = re.search(r"if deadline\.seconds > 0 and not args\.no_watchdog and deadline\.expired\(\):", src)
    ck(bool(m), "每节之间检查 deadline.expired()")
    ck("整轮时间上限到了" in src, "触发时有明确日志")

    m = re.search(
        r"watchdog_fired = watchdog\.force_close\(\s*"
        r"prog, reason=\"run-timeout\"[^)]*close_game=not args\.keep_game",
        src, re.S)
    ck(bool(m), "到点调 force_close(reason='run-timeout', close_game=…)")
    ck("args.keep_game" in src,
       "--keep-game 可豁免关游戏（调试用）")

    ck("state.set(\"result\", \"timeout\")" in src or 'state.set("result", "timeout")' in src,
       "state.result 落为 \"timeout\"")
    ck("state.set(\"watchdog\", watchdog_fired)" in src
       or 'state.set("watchdog", watchdog_fired)' in src,
       "state.watchdog 落盘（收尾明细）")

    print("\n[2] main.py —— 节点 8 的兜底不能超过总上限")
    m = re.search(r'if \(sid == "8" and args\.run_timeout > 0 and not args\.no_watchdog', src)
    ck(bool(m), "节点 8 起跑前把**剩余时间**传下去")
    ck("--total-timeout" in src, "经 --total-timeout 传递")
    print("        理由：超时检查粒度是「节」，若节点 8 自己的兜底比总上限还长，"
          "总上限只能在节点 8 **返回之后**才生效")

    print("\n[2b] ⚠️ 节点失败路径也必须能触发超时收尾（2026-10-17 实修）")
    print("        缺口：到点检查只在**每节开始前**跑；节点 8 拿到「剩余时间」当")
    print("        自己的兜底后会**抢先**报 timeout 返回 3，主控随即 break ——")
    print("        于是收尾分支永远不执行。实测现场留下 3 个进程（pythonw +")
    print("        NTEGame + HTGame），修复后同场景 0 残留、关游戏窗口 11 个。")

    m = re.search(
        r'if r\.returncode != 0:(.*?)\n            log\(f"\[主控\] 节点 \{sid\} 未通过 —— 链条在此停手"\)',
        src, re.S)
    ck(bool(m), "节点失败分支存在，且在里面插了超时判定")
    if m:
        blk = m.group(1)
        ck("deadline.expired()" in blk,
           "节点失败时**重新判定** deadline.expired()（这是修复的核心）")
        ck('reason="run-timeout"' in blk,
           "命中后调 force_close(reason='run-timeout')")
        ck('state.set("result", "timeout")' in blk, "并把 result 落为 timeout")
        ck("_report_after_timeout(" in blk, "调用统一的收尾复检")

    ck("def _report_after_timeout(" in src, "_report_after_timeout 已定义")
    ck(src.count("_report_after_timeout(prog, log)") >= 2,
       "两条超时路径（正常到点 / 节点失败报回）都走同一复检",
       f"调用 {src.count('_report_after_timeout(prog, log)')} 次")

    print("\n[2c] 复检必须**回读现场**，不能拿 force_close 的返回值下结论")
    m = re.search(r"def _report_after_timeout\(prog, log\):(.*?)\ndef ", src, re.S)
    ck(bool(m), "_report_after_timeout 函数体可取")
    if m:
        body = m.group(1)
        # ⚠️ 只看**可执行代码**，不搜整段文本 —— docstring 里特意写了
        #    「killed_game 为空不代表没清掉」这句解释，按纯文本搜会误报。
        code = "\n".join(
            ln for ln in body.splitlines()
            if not ln.strip().startswith("#"))
        # 去掉 """ ... """ docstring
        code = re.sub(r'""".*?"""', "", code, flags=re.S)

        ck("window.running(prog)" in code, "查目标程序残留")
        ck("watchdog.game_processes(prog)" in code, "查游戏残留")
        ck("not left_t and not left_g" in code, "两者皆空才报「干净」")
        ck("killed_game" not in code,
           "⚠️ **不**用 killed_game 做判断（只回读现场；仅文档里提及为何不信任它）")
        ck("需要人工处理" in code, "有残留时给出人工处理指引")

    print("\n[3] watchdog.py —— force_close 的能力")
    w = read(WATCHDOG_PY)
    ck("def force_close(" in w, "force_close 存在")
    for k in ("closed_windows", "closed_game_windows", "killed_target", "killed_game"):
        ck(k in w, f"返回结构含 {k}")
    ck("def game_windows(" in w, "game_windows（找游戏顶层窗口）存在")
    ck("def game_processes(" in w, "game_processes（找游戏进程）存在")
    ck("def _force_close_all(" in w, "_force_close_all（跨程序）存在")
    print("        ⚠️ program=None **不等于「全部」**，会回落到 programs.DEFAULT(ok-ww)；"
          "要清两个程序得传 all_programs=True")

    print("\n[4] 只读现场：残留应为 0")
    try:
        from orchestrator import programs, window, watchdog
        tot = 0
        for p in programs.ALL:
            t = window.running(p)
            g = watchdog.game_processes(p)
            print(f"        {p.display}: 程序={len(t)} 游戏={len(g)}")
            tot += len(t) + len(g)
        ck(tot == 0, "两程序两游戏残留为 0（若不为 0 说明上一次没清干净）")
    except Exception as e:  # noqa: BLE001
        ck(False, "只读现场探测", repr(e))


# ---------------------------------------------------------------- live 实测
def live(seconds=30.0):
    """真跑一次主控并把整轮上限压到 seconds，观察是否真的收尾。"""
    print(f"\n[5] live 实测：--run-timeout {seconds:.0f} 跑 ok-nte")
    print("        ⚠️ 会**真启动** ok-nte（并可能拉起游戏），需要管理员")
    import subprocess  # noqa: PLC0415
    import time  # noqa: PLC0415

    from orchestrator import programs, watchdog, window

    ts = time.strftime("%Y%m%d-%H%M%S")
    rd = os.path.join(ROOT, "logs", "runs", f"run-timeout-probe-{ts}")
    before_game = len(watchdog.game_processes(programs.NTE))
    print(f"        run-dir = {rd}")
    print(f"        起跑前游戏进程数 = {before_game}")

    cmd = [sys.executable, "-X", "utf8", "-m", "orchestrator.steps.main",
           "--target", "nte", "--run-timeout", f"{seconds:.0f}", "--run-dir", rd]
    print("        " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT)
    out = (p.stdout or "") + (p.stderr or "")

    ck("整轮时间上限到了" in out, "超时真的触发了")
    ck("run-timeout" in out, "reason 是 run-timeout")

    saw_game = "游戏无窗口可关" not in out
    print(f"        超时时是否已有游戏窗口可关 = {saw_game}")
    if not saw_game:
        print("        [注意] 这次超时早于游戏启动 ⇒ **关游戏这一半没被验到**。")
        print("               要么把 --run-timeout 调大到 120s 左右，要么按本文件")
        print("               顶部「实测记录」里的办法单独验游戏侧。")

    time.sleep(11)  # 收尾里有 10s 宽限
    left_t = window.running(programs.NTE)
    left_g = watchdog.game_processes(programs.NTE)
    ck(len(left_t) == 0, "收尾后目标程序已退出", f"剩 {len(left_t)}")
    if saw_game:
        ck(len(left_g) == 0, "收尾后游戏已退出", f"剩 {len(left_g)}")
    else:
        print(f"        （跳过游戏判定：超时时本来就没有游戏；现存 {len(left_g)}）")

    st_path = os.path.join(rd, "state.json")
    if os.path.exists(st_path):
        import json  # noqa: PLC0415
        st = json.load(open(st_path, encoding="utf-8"))
        ck(st.get("result") == "timeout", 'state.result == "timeout"',
           repr(st.get("result")))
        wd = st.get("watchdog") or {}
        ck(wd.get("reason") == "run-timeout",
           'state.watchdog.reason == "run-timeout"', repr(wd.get("reason")))
        ck(wd.get("target") == "nte", 'state.watchdog.target == "nte"',
           repr(wd.get("target")))
        print(f"        closed_windows      = {wd.get('closed_windows')}")
        print(f"        closed_game_windows = {wd.get('closed_game_windows')}")
    else:
        ck(False, "state.json 存在", st_path)

    print(f"\n        主控退出码 = {p.returncode}（超时收尾预期为 3）")
    print(f"        完整日志：{rd}\\stdout.log（若存在）")
    return p.returncode


def main():
    print("=" * 74)
    print("  整轮时间上限（RUN_TIMEOUT）超时收尾验证")
    print("=" * 74)
    static()
    if "--static" not in sys.argv:
        live()
    else:
        print("\n[5] live 实测已跳过（--static）")

    print("\n" + "=" * 74)
    if _fails:
        print(f"  结果：{_checks - len(_fails)}/{_checks} 通过；未过：{_fails}")
        return 1
    print(f"  结果：{_checks}/{_checks} 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
