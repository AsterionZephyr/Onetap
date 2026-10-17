"""FAULT #30 的 STALLED 分支 —— 真实卡死场景驱动脚本。

## 这个探针解决什么问题

`orchestrator/steps/step8_run_task.py` 有一段：

    检测到 ok-nte 执行器暂停（游戏窗口被最小化 →
    `og.executor.pause pos_invalid: (-32000, -32000)`）
    → 先给 `--stall-grace` 秒自行恢复 → 仍无任何业务行/收尾动作 → 判 STALLED

这段逻辑此前**只在单元测试和真实历史日志回归**里验过。
**2026-10-18 06:13:25 已用本脚本在真实卡死场景下跑通**（`--stall-grace 90`，正式值）：

    [阶段1] 已出现业务行 2 条 → ShowWindow(SW_MINIMIZE) 返回 True
    [哨兵] 06:14:32,699 ERROR update_window_size hwnd_window:og.executor.pause
            pos_invalid: (-32000, -32000, 0, 0)
    → 节点 8 用时 135.8s，status=failed，data.result='stalled'
    → state.result='stalled'，主控退出码 3
    → run-dir: logs/runs/stalled-live-20261018-061325

即「STALLED 映射为 **failed**（不是 timeout）」这条设计判据成立。

## 为什么需要它，而不是手工点

卡死要求三件事**同时**成立，手工做很难掐准时机：
  1. 游戏真的起来了；
  2. ok-nte 已经进入任务执行、正在写 `info_set`/`开始任务` 这类业务行；
  3. 这时**把游戏窗口最小化**，逼它写下哨兵 pause 然后停住。

本脚本按这个顺序自动推进：等游戏窗口 → 等 ok-nte 出现业务行 → 最小化 → 盯日志。

## 兜底与安全

- 无论成败，**结束时一定恢复窗口并清理进程**（finally 段）。
- 有总时限，不会无限等。
- 只把游戏窗口**最小化**（`ShowWindow(SW_MINIMIZE)`），不关闭、不修改目标程序。

## 跑法

    python -X utf8 probe/_probe_stalled_live.py --stall-grace 20 --wait-business 400

前提：**今天的 ok-nte 日常任务还没跑完**（否则它会直接收尾退出，不会有业务行）。
先看 `ok-script.log` 里 `开始执行日常任务` 是否已配 `结束执行日常任务`。
"""

import argparse
import ctypes
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from orchestrator import programs, verdict, watchdog, win32, window  # noqa: E402

NTE_LOG = os.path.join(programs.NTE.root_dir, "data", "apps", "ok-nte",
                       "working", "logs", "ok-script.log")
SW_MINIMIZE = 6


def log(msg):
    print(f"  {msg}", flush=True)


def minimize(hwnd):
    """最小化一个窗口。用 win32 的 ctypes 句柄约定（user32.ShowWindow）。"""
    return bool(ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE))


def game_main_hwnd():
    """找游戏**主窗口**（标题 `异环  `，UnrealWindow）。"""
    for h, pid, title, cls in watchdog.game_windows(programs.NTE):
        if "异环" in title:
            return h, title
    return None, None


def tail_since(offset):
    """读日志从 offset 起的增量文本（文件变小则整体读）。"""
    try:
        sz = os.path.getsize(NTE_LOG)
    except OSError:
        return "", offset
    with open(NTE_LOG, "rb") as f:
        if sz < offset:
            offset = 0
        f.seek(offset)
        data = f.read()
    return data.decode("utf-8", "replace"), sz


BIZ = re.compile(r"info_set (?:当前任务|轮次|当前阶段)|开始任务:|任务完成:|found Labels")
EXITISH = re.compile(r"ok:quit app|Executor destroy|Exiting early|Attempting to terminate")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stall-grace", type=float, default=20.0,
                    help="传给节点 8 的 --stall-grace（默认 20，正式值是 90）")
    ap.add_argument("--wait-business", type=float, default=900.0,
                    help="最多等多久等到 ok-nte 写出业务行。**必须给够**："
                         "实测 ok-nte 从启动到真正开始跑日常要 ~6.5 分钟"
                         "（12:06:45 launcher 就绪 → 12:13:13 才开始日常），"
                         "默认 420s 会在业务行出现前 11 秒就放弃")
    ap.add_argument("--hold", type=float, default=150.0,
                    help="最小化之后最多观察多久")
    ap.add_argument("--run-timeout", type=float, default=900.0,
                    help="主控整轮上限（要留够时间走到 STALLED）")
    args = ap.parse_args()

    print("=" * 74)
    print("  FAULT #30 —— STALLED 分支真实卡死验证")
    print("=" * 74)

    # --- 前置：今天还没跑完吗 -------------------------------------------
    text = ""
    if os.path.exists(NTE_LOG):
        with open(NTE_LOG, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    last_begin = text.rfind("DailyRoutineTask:开始执行日常任务")
    last_end = text.rfind("DailyRoutineTask:结束执行日常任务")
    if last_begin > 0 and last_begin > last_end:
        log("[前提] 今天的日常任务**已开始但未结束** —— 可以真跑 ✅")
    else:
        log("[前提] 今天没有「进行中的日常」—— ok-nte 可能直接收尾退出。")
        log("       仍继续，但若等不到业务行会如实报告。")

    ts = time.strftime("%Y%m%d-%H%M%S")
    rd = os.path.join(ROOT, "logs", "runs", f"stalled-live-{ts}")
    cmd = [sys.executable, "-X", "utf8", "-m", "orchestrator.steps.main",
           "--target", "nte", "--stall-grace", f"{args.stall_grace:.0f}",
           "--run-timeout", f"{args.run_timeout:.0f}", "--run-dir", rd]
    log(f"run-dir = {rd}")
    log("主控命令 = " + " ".join(cmd))

    # 日志基线：从这里开始看新增内容
    base = os.path.getsize(NTE_LOG) if os.path.exists(NTE_LOG) else 0
    off = base

    # ⚠️ FAULT #36（2026-10-18 实测）：**必须把主控 stdout 写进文件，不能用 PIPE**。
    #    原来的 `stdout=subprocess.PIPE` 在这段循环里**从不读取**，而主控与它
    #    `subprocess.run` 拉起的每个节点**继承同一个管道写端**。管道缓冲（64KB）
    #    写满后，主控和节点全部阻塞在 write 上 —— 整轮静默挂死，无异常、无退出码。
    #    实测现场：step5 节点存活 16 分钟、CPU 仅 0.03s、RSS 19MB（还没 import numpy）、
    #    线程 WaitReason=Executive、step5.log 恒为 0 字节 —— 就是「第一次写管道就卡住」。
    main_out = os.path.join(rd, "main.out.log")
    os.makedirs(rd, exist_ok=True)
    out_f = open(main_out, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=out_f,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    log(f"主控已启动（后台），stdout -> {main_out}")
    log("开始盯 ok-nte 的业务行与终端标记…")

    minimized = False
    min_at = None
    saw_pause = False
    biz_lines = []
    t_start = time.time()
    status = "未完成"

    try:
        while True:
            now = time.time()
            chunk, off = tail_since(off)
            if chunk:
                for line in chunk.splitlines():
                    if BIZ.search(line):
                        biz_lines.append(line.strip()[:110])
                    if verdict.NTE_EXECUTOR_PAUSE in line or "og.executor.pause" in line:
                        saw_pause = True
                        log(f"[哨兵] {line.strip()[:120]}")

            # 第 1 阶段：等业务行出现 → 立刻最小化
            if not minimized:
                if saw_pause:
                    log("[!!] 还没动手最小化，它自己就 pause 了（游戏被别的东西挡了？）")
                h, title = game_main_hwnd()
                if biz_lines and h:
                    log(f"[阶段1] 已出现业务行 {len(biz_lines)} 条，游戏主窗口 "
                        f"hwnd={h} '{title}' —— 现在最小化")
                    ok = minimize(h)
                    log(f"[阶段1] ShowWindow(SW_MINIMIZE) 返回 {ok}")
                    minimized = True
                    min_at = now
                elif now - t_start > args.wait_business:
                    status = "等业务行超时"
                    h_now, t_now = game_main_hwnd()
                    log(f"[阶段1] 等了 {args.wait_business:.0f}s 仍没等到"
                        f"「业务行 + 游戏主窗口」同时成立 —— 放弃，如实报告")
                    log(f"        业务行 {len(biz_lines)} 条；"
                        f"游戏主窗口 {'有' if h_now else '无'}"
                        f"{f' hwnd={h_now} {t_now!r}' if h_now else ''}")
                    if not biz_lines:
                        log("        ⇒ 注意区分两种情况：")
                        log("          (a) 等太短了 —— ok-nte 从启动到真跑日常"
                            "实测约 6.5 分钟，budget 要 >400s")
                        log("          (b) ok-nte 直接收尾了（今日已完成）——"
                            "看它的汇总行/终止标记")
                    break

            # 第 2 阶段：最小化之后盯 STALLED
            if minimized:
                held = now - min_at
                if saw_pause and held > args.stall_grace + 15:
                    status = "已进入暂停且超过宽限期"
                    log(f"[阶段2] 最小化 {held:.0f}s，已见哨兵 pause，"
                        f"宽限期 {args.stall_grace:.0f}s（+15s 余量）已过")
                    break
                if held > args.hold:
                    status = "观察窗口用尽"
                    log(f"[阶段2] 已观察 {held:.0f}s 达到上限，停止盯梢")
                    break

            if proc.poll() is not None:
                log(f"[!!] 主控提前退出，returncode={proc.returncode}")
                status = "主控提前退出"
                break
            time.sleep(1.0)

        # --- 等主控收尾 ---
        log("等待主控结束…")
        try:
            proc.wait(timeout=200)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        rc = proc.returncode
        try:
            out_f.flush()
        except Exception:  # noqa: BLE001
            pass
        with open(main_out, "r", encoding="utf-8", errors="replace") as f:
            out = f.read()

    finally:
        # --- 必须恢复窗口，并把现场清干净 -------------------------------
        log("")
        log("[收尾] 恢复游戏窗口 / 清理进程")
        try:
            h, title = game_main_hwnd()
            if h:
                log(f"  恢复 hwnd={h} '{title}'")
                win32.restore_window(h)
            else:
                log("  没有找到游戏主窗口（可能已退出）")
        except Exception as e:  # noqa: BLE001
            log(f"  恢复失败（忽略）：{e!r}")
        try:
            r = watchdog.force_close(None, all_programs=True,
                                     reason="probe-stalled-cleanup")
            for k, v in (r.get("per_program") or {}).items():
                log(f"  清理 {k}: 关目标窗口={len(v.get('closed_windows', []))} "
                    f"关游戏窗口={len(v.get('closed_game_windows', []))}")
            log(f"  leftover = {r.get('leftover')}")
        except Exception as e:  # noqa: BLE001
            log(f"  清理失败（忽略）：{e!r}")
        try:
            out_f.close()
        except Exception:  # noqa: BLE001
            pass

    # --- 判定 -----------------------------------------------------------
    print("\n" + "=" * 74)
    print("  结果")
    print("=" * 74)
    log(f"主控退出码 = {rc}")
    log(f"业务行捕获 = {len(biz_lines)} 条")
    for b in biz_lines[-5:]:
        log(f"    {b}")
    log(f"是否见到哨兵 pause = {saw_pause}")
    log(f"是否最小化过 = {minimized}")
    log(f"盯梢结束原因 = {status}")

    # ⚠️ 判定必须以 **state.json 的 result 为准**，不能只 grep stdout 的大写 "STALLED"。
    #    2026-10-18 实测踩过：主控把结论写成小写 `stalled`（`[结果] stalled：...`），
    #    只 grep 大写会**把已经触发成功的轮次误报为「未触发」**。
    st = os.path.join(rd, "state.json")
    state_result = None
    if os.path.exists(st):
        import json  # noqa: PLC0415
        d = json.load(open(st, encoding="utf-8"))
        state_result = d.get("result")
        log(f"state.result = {state_result!r}")
        log(f"state.result_detail = {str(d.get('result_detail'))[:150]!r}")
        step8 = (d.get("steps") or {}).get("8") or {}
        log(f"steps.8.status = {step8.get('status')!r}")
        log(f"steps.8.data = {str(step8.get('data'))[:200]!r}")
    log(f"运行目录 = {rd}")

    stalled_seen = (state_result == "stalled"
                    or "stalled" in (out or "").lower()
                    or "执行器已暂停" in (out or ""))
    log(f"确认 STALLED（state.result 或主控输出）= {stalled_seen}")
    if stalled_seen:
        for line in (out or "").splitlines():
            if "stalled" in line.lower() or "执行器已暂停" in line:
                log(f"    {line.strip()[:130]}")

    print("\n" + "=" * 74)
    if stalled_seen:
        print("  ✅ STALLED 分支已在真实卡死场景下触发")
        return 0
    print(f"  ⚠️ 未触发 STALLED（结束原因：{status}）—— 如实报告，不掩盖")
    return 1


if __name__ == "__main__":
    sys.exit(main())
