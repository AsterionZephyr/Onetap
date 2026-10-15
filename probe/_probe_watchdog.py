"""探针：watchdog 超时收尾的端到端验证（不碰真实目标程序）。

设计：**不**去起真的 ok-ww / ok-nte（那要几分钟且会真的开游戏）。
改为起两个**同名的假进程**，让 watchdog 按 `process_prefix` / `game_names`
把它们认出来，然后验证 force_close 确实关窗 + 杀进程。

假目标程序：往 G:\\... 不行 —— process_prefix 是写死的真实路径。
故本探针分两段：

  [A] 单元段：用临时 Program 记录（process_prefix 指向临时目录、
      game_names 指向假游戏进程名），验证识别与关闭逻辑。
      这一段**完全不需要真实程序**。
  [B] 真实段：只在真实目标在跑时才有意义，默认跳过；
      加 --live 才跑。

用法：
    python probe/_probe_watchdog.py            # 只跑 [A]
    python probe/_probe_watchdog.py --live     # 额外做真实巡视（只读）
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import programs as programs_mod   # noqa: E402
from orchestrator import watchdog                   # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_fake_program(tmpdir, game_names):
    """造一条临时 Program 记录，指向临时目录 + 指定的假游戏名。"""
    return programs_mod.Program(
        key="fake", display="假目标",
        exe=str(Path(tmpdir) / "fake.exe"),
        root_dir=str(tmpdir),
        process_prefix=str(tmpdir),
        process_names=["python.exe", "pythonw.exe"],
        loose_title_re=r"(?i)fake-target-xyz",
        ready_title_re=r"(?i)fake-target-xyz",
        min_width=10, min_height=10,
        game_names=game_names,
    )


def spawn_python(script_body, *args):
    """起一个长跑 python 子进程，返回 Popen。"""
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", script_body, *args],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


SLEEPER = "import time; time.sleep(120)"


def main():
    live = "--live" in sys.argv
    print("=" * 70)
    print("watchdog 探针")
    print("=" * 70)

    # ---------------- [A1] Deadline 语义 ----------------
    print("\n[A1] Deadline 语义")
    d = watchdog.Deadline(0)
    d.begin()
    check("上限 0 ⇒ 永不 expired（0 = 不限制）", not d.expired())
    d = watchdog.Deadline(0.01)
    d.begin()
    time.sleep(0.05)
    check("上限 0.01s ⇒ expired", d.expired())
    check("remaining() 不为负", d.remaining() == 0.0, f"remaining={d.remaining()}")

    # ---------------- [A2] 进程识别 ----------------
    print("\n[A2] 按 process_prefix 识别「目标程序」")
    tmp = tempfile.mkdtemp(prefix="wdprobe-")
    fake = make_fake_program(tmp, ["fake-game-proc.exe"])

    # 起一个 python 长跑进程，用**它自己的真实路径**做归属判定 ——
    # 但 process_prefix 是 tmp，python.exe 不在 tmp 下，故它**不该**被认成目标。
    p_out = spawn_python(SLEEPER)
    try:
        time.sleep(1.0)
        from orchestrator import window
        alive = window.running(fake)
        check("外部 python 进程**不该**被认成假目标（前缀不匹配）",
              not alive, f"alive={[(n, pid) for n, pid, _ in alive]}")

        # 反过来：把 process_prefix 设成 python.exe 所在目录，它就**该**被认出。
        py_dir = os.path.dirname(sys.executable)
        fake2 = make_fake_program(py_dir, [])
        alive2 = window.running(fake2)
        check("process_prefix 指向 python 目录 ⇒ 能认出该进程",
              any(pid == p_out.pid for _, pid, _ in alive2),
              f"找到 {[(n, pid) for n, pid, _ in alive2][:4]} 个")
    finally:
        p_out.kill()

    # ---------------- [A3] game_names 判据 ----------------
    print("\n[A3] 游戏进程按**进程名**判定（不看路径）")
    from orchestrator import win32
    # 本机没有真的 Steam/鸣潮在跑，就验证反向：不存在的名字应返回空
    got = watchdog.game_processes(
        programs_mod.Program(
            key="x", display="x", exe="x", root_dir="x", process_prefix="x",
            process_names=[], loose_title_re="x", ready_title_re="x",
            min_width=1, min_height=1,
            game_names=["definitely-not-a-real-process-xyz.exe"]))
    check("不存在的游戏进程名 ⇒ 空列表", got == [], f"got={got}")

    real_game = win32.list_processes(["HTGame.exe", "NTEGame.exe",
                                      "Client-Win64-Shipping.exe"])
    print(f"        （本机现存的目标游戏进程：{[(n, p) for n, p, _ in real_game]}）")

    # ---------------- [A4] 关窗 API 可用 ----------------
    print("\n[A4] close_window 必须是「指定的那一个窗口」，不是广播")
    # ⚠️ 这条是实打实的危险点，不是形式检查：
    # Win32 把 hwnd=0 当 HWND_BROADCAST，PostMessageW(0, WM_CLOSE) 会
    # **把整个桌面的窗口都关掉**。必须显式拒绝。
    for bad, label in ((0, "0"), (None, "None")):
        try:
            r = watchdog.close_window(bad)
            check(f"句柄 {label} ⇒ 必须 False（否则会广播 WM_CLOSE）",
                  r is False, f"返回 {r}")
        except Exception as e:
            check(f"句柄 {label} ⇒ False（且不抛异常）", False,
                  f"抛了 {type(e).__name__}: {e}")

    # ---------------- [A5] force_close 在「什么都没有」时安全 ----------------
    print("\n[A5] force_close 在无目标无游戏时应安全返回（dry_run）")
    try:
        res = watchdog.force_close(fake, reason="probe", dry_run=True)
        check("返回 dict 且有 reason", isinstance(res, dict)
              and res.get("reason") == "probe", f"{res}")
        check("dry_run 时不杀任何进程", not res.get("killed_target"),
              f"killed_target={res.get('killed_target')}")
    except Exception as e:
        check("force_close 不抛异常", False, f"{type(e).__name__}: {e}")

    # ---------------- [B] 真实巡视（只读）----------------
    if live:
        print("\n[B] 真实巡视（只读，不动任何东西）")
        for p in programs_mod.ALL:
            watchdog.survey(p, log=print)
            print()

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 70)
    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("全部通过")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
