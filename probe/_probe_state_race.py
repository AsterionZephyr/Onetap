"""探针：`state.json` 原子替换与「读轮询」的撞车窗口（FAULT #37）。

## 背景（2026-10-18 真实故障）

用户在 GUI 里跑整条链，节点 6 报：

    PermissionError: [WinError 5] 拒绝访问。:
      '...\\logs\\runs\\run-20261018-131146\\state.json.tmp'
      -> '...\\logs\\runs\\run-20261018-131146\\state.json'

`orchestrator/steps/context.py` 的 `RunState.save()` 用的是
「写 tmp + `os.replace`」原子替换。在 Windows 上，
`MoveFileExW(MOVEFILE_REPLACE_EXISTING)` 遇到**目标文件正被别的进程打开**
（哪怕只是只读打开）就返回 `ERROR_ACCESS_DENIED`(5) ——
因为 CPython 的 `open()` 只共享 READ|WRITE，**不共享 DELETE**。
而 GUI 侧 `gui/runner.py::StateWatcher.poll()` 每 120 ms 打开一次
`state.json` 读 JSON。两边撞上就抛这个异常。

## 两种跑法

### 1. 测撞车率（裸 `os.replace`，不重试）

    python -X utf8 probe/_probe_state_race.py --seconds 25 --poll-ms 120
    python -X utf8 probe/_probe_state_race.py --seconds 8  --poll-ms 0    # 负向对照

父进程按 GUI 的节奏**跨进程**轮询 `state.json`；子进程反复「写 tmp + os.replace」。
`--poll-ms 0`（不轮询）必须 0 失败，否则是探针自身的问题。

### 2. 验证修复（走**真实** `RunState.save()`）

    python -X utf8 probe/_probe_state_race.py --verify-fix --seconds 12
    python -X utf8 probe/_probe_state_race.py --verify-fix --raw --seconds 12  # 负向对照

`--verify-fix` 用真实的 `RunState` 反复 `set()+save()`，同时另一进程照 GUI 节奏轮询。
`--raw` 会把 `RunState.save` 临时换回**不重试**的旧实现 —— 用来证明这个夹具
**确实能抓到**该故障（不带 `--raw` 时 0 失败才有意义）。

## 判定

- 负向对照（`--poll-ms 0` 或 `--raw`）必须**复现失败**，否则夹具无效。
- 修复后（`--verify-fix`）必须 **0 失败**。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable


def _payload(n):
    """一份形状贴近真实 state.json 的载荷（约 3 KB，含中文）。"""
    return {
        "run_dir": "X",
        "started_at": "2026-10-18 13:11:46",
        "dry_run": False,
        "steps": {
            str(i): {"name": f"节点{i}", "status": "ok",
                     "notes": ["撞车测试 ✓ 中文载荷"], "shots": ["shots/001-x.png"]}
            for i in range(1, 10)
        },
        "seq": n,
    }


# ---------------------------------------------------------------------------
# 子进程：写入侧（模拟节点 save() 的裸实现）
# ---------------------------------------------------------------------------

def child_writer(path, seconds, stats_path):
    tmp = path + ".tmp"
    ok = bad = 0
    codes = {}
    t_end = time.time() + seconds
    while time.time() < t_end:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_payload(ok), f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, path)
            ok += 1
        except OSError as e:
            bad += 1
            key = str(getattr(e, "winerror", "?"))
            codes[key] = codes.get(key, 0) + 1
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "bad": bad, "codes": codes}, f, ensure_ascii=False)
    print(f"[writer] 成功 {ok} 次，失败 {bad} 次，错误码 {codes}", flush=True)


# ---------------------------------------------------------------------------
# 子进程：读侧（模拟 GUI StateWatcher）
# ---------------------------------------------------------------------------

def child_reader(path, seconds, poll_ms):
    reads = errors = 0
    t_end = time.time() + seconds
    while time.time() < t_end:
        if poll_ms > 0 and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json.load(f)
                reads += 1
            except (OSError, ValueError):
                errors += 1
        time.sleep(max(poll_ms, 1) / 1000.0)
    print(f"[reader] 读 {reads} 次，异常 {errors} 次（间隔 {poll_ms}ms）", flush=True)


# ---------------------------------------------------------------------------
# 夹具：真实 RunState.save() 对跨进程轮询
# ---------------------------------------------------------------------------

def _spawn(args, log_path):
    out = open(log_path, "w", encoding="utf-8")        # ⚠️ 落文件，不挂 PIPE（FAULT #36）
    proc = subprocess.Popen(
        [PY, "-X", "utf8", os.path.abspath(__file__)] + args,
        stdout=out, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return proc, out


def verify_fix(seconds, raw):
    sys.path.insert(0, ROOT)
    from orchestrator.steps import context as ctx          # noqa: PLC0415

    if raw:
        def _raw_save(self):
            os.makedirs(self.run_dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.raw, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)                      # 旧实现：不重试
        ctx.RunState.save = _raw_save

    work = os.path.join(ROOT, "logs", "tmp-state-race-fix")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    st = ctx.RunState(work)
    st.set("program", "ww")
    st.save()

    proc, out = _spawn(["--child-reader", st.path, str(seconds), "120"],
                       os.path.join(work, "reader.out.log"))
    ok = bad = 0
    codes = {}
    t_end = time.time() + seconds
    while time.time() < t_end:
        st.set("seq", ok)
        try:
            st.save()
            ok += 1
        except OSError as e:
            bad += 1
            key = str(getattr(e, "winerror", "?"))
            codes[key] = codes.get(key, 0) + 1
    proc.wait()
    out.close()

    total = ok + bad
    rate = (bad / total * 100.0) if total else 0.0
    print("=" * 70)
    print(f"  实现        {'裸 os.replace（旧，不重试）' if raw else 'RunState.save（当前实现）'}")
    print(f"  替换次数    {total}（成功 {ok} / 失败 {bad}）")
    print(f"  错误码      {codes}")
    print(f"  撞车率      {rate:.3f}%")
    print("=" * 70)
    if raw:
        print("  负向对照：" + ("✅ 如实复现了 WinError 5（夹具有效）"
                              if bad else "❌ 没复现 —— 夹具或机器有问题，别信修复结论"))
        return 0 if bad else 1
    print("  修复结论：" + ("✅ 0 失败，重试把撞车吃掉了"
                          if bad == 0 else f"❌ 仍失败 {bad} 次，重试不够"))
    return 0 if bad == 0 else 1


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def measure(poll_ms, seconds):
    work = os.path.join(ROOT, "logs", "tmp-state-race")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    path = os.path.join(work, "state.json")
    stats = os.path.join(work, "stats.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_payload(0), f, ensure_ascii=False, indent=2)

    proc, out = _spawn(["--child-writer", path, str(seconds), stats],
                       os.path.join(work, "writer.out.log"))
    reads = 0
    t_end = time.time() + seconds
    while time.time() < t_end and proc.poll() is None:
        if poll_ms > 0 and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json.load(f)
                reads += 1
            except (OSError, ValueError):
                pass
        time.sleep(max(poll_ms, 1) / 1000.0 if poll_ms > 0 else 0.05)
    proc.wait()
    out.close()

    with open(stats, encoding="utf-8") as f:
        stt = json.load(f)
    total = stt["ok"] + stt["bad"]
    rate = (stt["bad"] / total * 100.0) if total else 0.0
    print("=" * 70)
    print(f"  轮询间隔    {poll_ms} ms（{reads} 次读）")
    print(f"  替换次数    {total}（成功 {stt['ok']} / 失败 {stt['bad']}）")
    print(f"  错误码      {stt['codes']}")
    print(f"  撞车率      {rate:.3f}%")
    print("=" * 70)
    if poll_ms <= 0:
        print("  负向对照：" + ("✅ 0 失败，探针自身没问题"
                              if stt["bad"] == 0 else "❌ 不轮询也失败，探针有问题"))
        return 0 if stt["bad"] == 0 else 1
    print("  结论：" + ("✅ 撞车窗口真实存在（读轮询与原子替换互斥）"
                      if stt["bad"] else "⚠️ 本轮没撞上 —— 窗口存在但概率低，多跑几轮"))
    return 0


def main():
    ap = argparse.ArgumentParser(description="state.json 原子替换撞车率测量 / 修复验证")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--poll-ms", type=int, default=120,
                    help="读轮询间隔，0 = 负向对照（不轮询）")
    ap.add_argument("--verify-fix", action="store_true",
                    help="走真实 RunState.save() 验证重试修复")
    ap.add_argument("--raw", action="store_true",
                    help="配合 --verify-fix：换回不重试的旧实现作负向对照")
    ap.add_argument("--child-writer", nargs=3, metavar=("PATH", "SEC", "STATS"))
    ap.add_argument("--child-reader", nargs=3, metavar=("PATH", "SEC", "POLL_MS"))
    a = ap.parse_args()

    if a.child_writer:
        child_writer(a.child_writer[0], float(a.child_writer[1]), a.child_writer[2])
        return 0
    if a.child_reader:
        child_reader(a.child_reader[0], float(a.child_reader[1]),
                     int(a.child_reader[2]))
        return 0
    if a.verify_fix:
        return verify_fix(a.seconds, a.raw)
    return measure(a.poll_ms, a.seconds)


if __name__ == "__main__":
    sys.exit(main())
