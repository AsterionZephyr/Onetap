"""q3_pid_identity.py — 核实：ok-ww 关不掉的那个 PID 到底是谁

假设 H1：是 Tauri 启动器 ok-ww.exe
假设 H2：该进程**其实已经退出**了，Windows 对已退出的 PID 返回 ACCESS_DENIED

判别方法：看日志中该 PID 在别处是否出现过，以及 Attempting->Failed 之间隔了多久。
如果"Failed"紧跟"Attempting"（毫秒级），且该 PID 在进程表里从未被我们观察到，
则 H2 更可能。
"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LOGDIR = Path(r"E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs")


def main():
    print("=" * 78)
    print("核实：关不掉的 PID 的身份")
    print("=" * 78)

    for f in sorted(LOGDIR.glob("ok-script*.log")):
        t = f.read_text(encoding="utf-8", errors="replace")
        # 找 Attempting / Failed 的配对，看间隔
        pairs = re.findall(
            r"(\d\d:\d\d:\d\d,\d+) INFO PyAppifyShutdown ok:Attempting to terminate process with PID:? (\d+).*?"
            r"(?:(\d\d:\d\d:\d\d,\d+) ERROR PyAppifyShutdown ok:Failed to terminate process with PID (\d+))?",
            t, re.S)
        if not pairs:
            continue
        print(f"\n--- {f.name} ---")
        for a_time, a_pid, f_time, f_pid in pairs[-3:]:
            if f_time:
                print(f"  Attempting PID={a_pid} @ {a_time}")
                print(f"  Failed     PID={f_pid} @ {f_time}   （同名={a_pid == f_pid}）")
            else:
                print(f"  Attempting PID={a_pid} @ {a_time}   （无失败记录 => 成功终止）")

        # 该 PID 在日志别处出现过吗？
        pids = set(re.findall(r"PID:? (\d+)", t))
        print(f"  日志中出现的所有 PID: {sorted(pids)}")

        # 找 pythonw / launcher 相关的进程创建记录
        for pat, label in [
            (r"use_pythonw", "use_pythonw 配置"),
            (r"Kill Launcher After Start", "启动后杀启动器"),
            (r"Attempting to minimize window for process with PID:? (\d+)", "最小化的进程"),
        ]:
            m = re.findall(pat, t)
            if m:
                print(f"  [{label}] {m[:3]}")

    print("\n" + "=" * 78)
    print("判定")
    print("=" * 78)
    print("""
关键线索：日志中有 'MainWindow showEvent Kill Launcher After Start'
        => ok-ww **主动设计为"启动后杀掉启动器"**。
        => PyAppifyShutdown 阶段要终止的那个 PID 就是**第一层启动器 ok-ww.exe**。

而 [WinError 5] 拒绝访问 有两种成因：
  (a) 启动器以更高完整性运行，我们（第二层）无权终止；
  (b) 启动器**已经退出**，对已失效 PID 的 OpenProcess 返回 ACCESS_DENIED。

无论 (a) 还是 (b)，对本框架的结论相同：
  => **不能依赖 ok-ww 自己清理干净**，编排层应做兜底强制清理。
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
