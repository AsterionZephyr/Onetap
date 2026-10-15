"""验证 on_run 是否真的能起子进程 —— 绕开鼠标，直接驱动。

目的：区分两种"点了没反应"：
  (a) 按钮的 <Button-1> 没绑上 / command 没接上  → GUI 缺陷
  (b) on_run 跑起来了但子进程起不来 / 立刻退出     → 编排缺陷

本探针直接调 `a.on_run()`，看 runner 是否真的拉起进程。
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def main():
    from gui import app as app_mod

    a = app_mod.App()
    a.update()
    for _ in range(20):
        a.update()
        time.sleep(0.03)

    print("python_var =", a.python_var.get())
    print("dry_run    =", a.dry_run.get())
    print("only_var   =", repr(a.only_var.get()))
    print("resume     =", a.resume_var.get())
    print("is_running =", a.runner.is_running())
    print("btn_run state =", a.btn_run.cget("state"))

    print("--- 调 on_run() ---")
    t0 = time.time()
    try:
        a.on_run()
    except Exception as e:
        import traceback
        print("on_run 抛异常：", repr(e))
        traceback.print_exc()
        a.destroy()
        return 1

    print(f"on_run 返回，用时 {time.time()-t0:.2f}s")
    print("is_running =", a.runner.is_running())
    print("btn_run state =", a.btn_run.cget("state"))
    print("btn_stop state =", a.btn_stop.cget("state"))
    proc = getattr(a.runner, "proc", None)
    print("proc =", proc)

    # 泵 10 秒，收集日志
    deadline = time.time() + 10
    lines = []
    while time.time() < deadline:
        a.update()
        try:
            while True:
                kind, payload = a.bus.q.get_nowait()
                if kind == "log":
                    lines.append(payload[0])
        except Exception:
            pass
        time.sleep(0.05)

    print(f"--- 泵到 {len(lines)} 行日志 ---")
    for ln in lines[:60]:
        print("  |", ln)

    print("--- 再查状态 ---")
    print("is_running =", a.runner.is_running())
    if proc:
        print("proc.poll() =", proc.poll())

    # 收尾：如果还活着，杀掉整树
    if a.runner.is_running():
        print("仍在运行，调用 stop()")
        print("stop ->", a.runner.stop())

    a.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
