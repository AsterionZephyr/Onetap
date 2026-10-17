"""probe/_probe_gui_both_live.py — 用**真实 App** 驱动 GUI 跑一次 --target both

为什么不用点击：HANDOFF.md §10 第 7 条 —— 远程会话（GameViewer）下 Tk 窗口
收不到合成点击。`desktop_click` 会报告落点与目标一致，但 `ttk.Button` /
`ttk.Combobox` 毫无反应。所以这个探针走**程序化路径**：

  1. 建**真的** `gui.app.App`（真的 tk 窗口、真的 Runner、真的 StateWatcher）；
  2. 把目标选择器设成「两个都跑」；
  3. 调**真实的 `App.on_run()`**（不是复刻一份参数拼接逻辑）；
  4. 自己把 `_work` 跑在本线程（`on_run` 本来会另起线程，我们要能观察）；
  5. 边跑边 `update()` 让 Tk 处理事件，同时把 bus 上的日志/节点状态收集下来；
  6. 结束后核对：子进程退出码、日志里有没有 `--target both`、串联汇总行、
     两轮节点状态是否都到了 ok。

跑法（在仓库根）：
    python -X utf8 probe/_probe_gui_both_live.py            # 真跑，约 20 分钟
    python -X utf8 probe/_probe_gui_both_live.py --dry-run  # 只跑节点 1，快
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑节点 1（--only 1）且带 --dry-run，几十秒即可")
    ap.add_argument("--timeout", type=float, default=1500.0,
                    help="本次驱动的总上限（秒），到点就停并报 NG")
    ap.add_argument("--only", default="",
                    help="只跑某节点（叠加在 both 上，仅用于排障）")
    args = ap.parse_args()

    print("  GUI 端到端：用真实 App 驱动 --target both")
    print("  " + "=" * 72)

    import tkinter as tk
    import gui.app as A

    # ---- 1. 建真的 App（真的窗口、真的 Runner / StateWatcher）----
    import gui.elevate as elev
    app = A.App(dry_run=False, only=None)

    # 收起窗口但不要 destroy —— 我们要它活着跑完
    try:
        app.geometry("1280x780+40+40")
    except tk.TclError:
        pass

    print(f"  1. App 已建：python_var={app.python_var.get()}")
    print(f"     TARGET_CHOICES = {A.TARGET_CHOICES}")
    print(f"     TARGET_ARG     = {A.TARGET_ARG}")

    # ---- 2. 选目标程序：两个都跑 ----
    both_label = None
    for lab, arg in A.TARGET_ARG.items():
        if arg == "both":
            both_label = lab
    if both_label is None:
        print("  [NG] TARGET_ARG 里没有 both")
        return 1
    app.target_var.set(both_label)
    print(f"  2. 目标选择器 = {both_label!r} -> --target {A.TARGET_ARG[both_label]}")

    # 只跑节点（可选，仅排障用）
    if args.only:
        app.only_var.set(args.only)
    if args.dry_run:
        app.dry_run.set(True)
        if not args.only:
            app.only_var.set("1")
    print(f"     dry_run={app.dry_run.get()} only={app.only_var.get()!r} "
          f"resume={app.resume_var.get()}")

    # ---- 3. 收集 bus 上的东西 ----
    logs = []
    nodes = {}      # sid -> 最后一次 status
    done = {"flag": False, "code": None}

    orig_log = app.runner.bus.log

    def spy_log(text, kind=None):
        logs.append(text)
        if len(logs) % 40 == 0:
            print(f"     … 已收 {len(logs)} 行，末行：{text[:100]}")
        return orig_log(text, kind=kind)

    app.runner.bus.log = spy_log

    orig_node = app.runner.bus.node

    def spy_node(sid, name, status, note=None, elapsed=None):
        nodes[sid] = status
        return orig_node(sid, name, status, note=note, elapsed=elapsed)

    app.runner.bus.node = spy_node

    # _work 结束时会调它自己的收尾；我们包一层记下退出码
    orig_work = app._work

    def wrapped_work():
        try:
            orig_work()
        finally:
            done["flag"] = True
            p = app.runner.proc
            done["code"] = p.poll() if p is not None else None

    app._work = wrapped_work

    # ---- 4. 调真实的 on_run() ----
    print("  3. 调真实 App.on_run() …")
    app.on_run()
    proc = app.runner.proc
    if proc is None:
        print("  [NG] on_run 之后 runner.proc 仍是 None —— 没起子进程")
        return 1
    print(f"     子进程已起：pid={proc.pid}")

    # ---- 5. 抽干事件循环直到子进程结束 ----
    t0 = time.time()
    last_tick = t0
    while not done["flag"]:
        try:
            app.update()          # 让 Tk 处理事件（含 StateWatcher 的 after 轮询）
        except tk.TclError as e:
            print(f"     [注意] Tk 报错：{e}")
            break
        if time.time() - t0 > args.timeout:
            print(f"  [NG] 超过 {args.timeout:.0f}s 仍未结束，终止进程树")
            try:
                print("     " + app.runner.stop())
            except Exception as e:
                print(f"     stop 异常：{e}")
            break
        if time.time() - last_tick > 30:
            last_tick = time.time()
            el = time.time() - t0
            print(f"     … +{el:.0f}s  日志 {len(logs)} 行  "
                  f"节点状态 {sorted((k, v) for k, v in nodes.items())}")
        time.sleep(0.05)

    # 再抽一会儿，让尾部日志出来
    for _ in range(40):
        try:
            app.update()
        except tk.TclError:
            break
        time.sleep(0.05)

    el = time.time() - t0
    print(f"  4. 结束：退出码={done['code']} 用时 {el:.1f}s 日志 {len(logs)} 行")

    # ---- 6. 核对 ----
    print("  " + "-" * 72)
    print("  核对")
    text = "\n".join(logs)
    checks = []

    checks.append(("日志里出现 --target both",
                   "--target both" in text))
    checks.append(("出现「串联第 1 轮」",
                   "串联第 1 轮" in text))
    checks.append(("出现「串联第 2 轮」",
                   "串联第 2 轮" in text))
    checks.append(("出现「串联汇总」",
                   "串联汇总" in text))
    checks.append(("出现「串联复检」",
                   "串联复检" in text))
    checks.append(("退出码为 0", done["code"] == 0))

    # 两轮各自的节点状态。
    # ⚠️ **不能只看 bus 推来的 nodes** —— bus.node 只在**状态变化**时触发，而
    # 短跑（dry-run 2.5s）会在 Tk 的 after 轮询第一次跑起来之前就结束，于是
    # nodes 永远为空。这**不是接线坏了**，是探针的观测方式不对（实测踩过：
    # 干跑那次 nodes 实得 0，但 state.json 里 ww/nte 的 steps 都是 {'1':'ok'}）。
    # 权威来源是落盘的 state.json。
    import json as _json
    rd_ = getattr(app, "run_dir", None)
    per_sub = {}
    if rd_ and os.path.isdir(rd_):
        for sub in ("ww", "nte"):
            sp = os.path.join(rd_, sub, "state.json")
            if not os.path.isfile(sp):
                per_sub[sub] = None
                continue
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    per_sub[sub] = _json.load(f)
            except (OSError, ValueError):
                per_sub[sub] = None

    ok_subs = []
    for sub, raw in per_sub.items():
        st = {k: v.get("status") for k, v in ((raw or {}).get("steps") or {}).items()}
        if st and all(v == "ok" for v in st.values()):
            ok_subs.append(sub)
        print(f"      {sub}: steps={st} result={(raw or {}).get('result')}")

    checks.append((f"两轮各有一套 all-ok 的节点状态（实得 {ok_subs}）",
                   len(ok_subs) == 2))

    badstatus = []
    for sub, raw in per_sub.items():
        for k, v in ((raw or {}).get("steps") or {}).items():
            if v.get("status") in ("failed", "timeout"):
                badstatus.append(f"{sub}/{k}={v.get('status')}")
    checks.append((f"没有 failed/timeout（实得 {badstatus}）", not badstatus))

    for name, ok in checks:
        print(f"    [{'OK ' if ok else 'NG '}] {name}")

    # 尾部落盘线索
    rd = getattr(app, "run_dir", None)
    print(f"    run_dir = {rd}")
    if rd and os.path.isdir(rd):
        for sub in sorted(os.listdir(rd)):
            print(f"      {sub}")

    try:
        app.destroy()
    except tk.TclError:
        pass

    nfail = sum(1 for _, ok in checks if not ok)
    print("  " + "=" * 72)
    if nfail:
        print(f"  {nfail} 项未通过")
        return 1
    print("  全部通过 —— GUI 真的把 --target both 跑起来了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
