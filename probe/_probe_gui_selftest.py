"""GUI 骨架的集成自检：验证线程/队列边界真的能跑通。

这是骨架最容易被埋坑的地方 —— tkinter 不是线程安全的，
worker 绝不能让 widget 操作跑在自己线程里。

本脚本用真实的 App + 真实的 worker 线程跑一次 dry-run，
断言：事件确实从 worker 流到主线程、节点状态确实被更新。
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import win32
win32.ensure_dpi_aware()

from orchestrator.gui import App


def main():
    app = App(dry_run=True)
    app.withdraw()

    print("=== GUI 线程/队列边界集成自检 ===")
    print("1. 主线程 id            :", threading_id())

    # 记录 worker 线程 id，确认事件不是从主线程发出的
    import threading
    workers = []
    orig_run = app.on_run

    def spy_run():
        orig_run()

        def tap():
            workers.append(app.worker.ident)
        app.after(50, tap)

    app.on_run = spy_run
    app.on_run()

    # 让事件循环真的跑起来（不是 sleep，是 mainloop 的 update）
    deadline = time.time() + 25
    ticks = 0
    while time.time() < deadline:
        app.update()          # 处理 after() 与队列
        ticks += 1
        if app.btn_run["state"] == "normal" and ticks > 20:
            break
        time.sleep(0.05)

    print("2. worker 线程 id       :", workers[0] if workers else "（未捕获）")
    print("3. 主线程 != worker     :", workers and workers[0] != threading_id())

    # 队列必须已排空（主线程消费掉了）
    print("4. 队列剩余事件         :", app.bus.q.qsize())

    # 节点状态：dry-run 下节点 1..7 应至少被标记过
    states = {}
    for idx, row in app.node_rows.items():
        states[idx] = row["dot"]["text"]
    print("5. 各节点最终标记       :", states)

    log_lines = int(app.log_text.index("end-1c").split(".")[0])
    print("6. 日志行数             :", log_lines)

    ok = True
    if not (workers and workers[0] != threading_id()):
        print("   [FAIL] worker 未在独立线程运行")
        ok = False
    if log_lines < 5:
        print("   [FAIL] 日志为空，事件未送达主线程")
        ok = False
    marked = [i for i, s in states.items() if s in ("✔", "▶")]
    if not marked:
        print("   [FAIL] 没有任何节点被标记")
        ok = False

    app.destroy()
    print()
    print("结果:", "通过" if ok else "失败")
    return 0 if ok else 1


def threading_id():
    import threading
    return threading.get_ident()


if __name__ == "__main__":
    sys.exit(main())
