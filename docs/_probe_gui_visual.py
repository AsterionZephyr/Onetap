"""验证「节点高亮」在实际运行中是否可见 —— 不依赖合成点击。

前面用 desktop_click 驱动失败（前台被 Chrome 抢走），
故改为：在进程内直接触发 on_run，并在运行**中途**截图窗口，
用肉眼确认节点 1 真的变成了 running 样式。

做法：把 worker 换成一个会停留几秒的假编排，这样能截到 mid-flight 的状态。
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import win32
win32.ensure_dpi_aware()

from orchestrator.gui import App

HOLD_SECONDS = float(os.environ.get("HOLD", "6"))


def fake_worker(bus, dry_run):
    """假编排：依次点亮节点，每步停一下，最后停下等截图。"""
    bus.log("=== 假编排（仅用于验证 GUI 高亮）===")
    for idx, name in [(1, "提权检查"), (2, "启动 ok-ww.exe"), (4, "等待第二层"),
                      (5, "等待窗口就绪")]:
        bus.node(idx, name, "running")
        bus.log(f"\n[节点 {idx}] {name}")
        time.sleep(0.6)
        bus.log(f"  [OK] 节点 {idx} 完成")
        bus.node(idx, "", "done")
    bus.node(6, "抓首帧校验", "running")
    bus.log("\n[节点 6] 抓首帧校验")
    bus.log("  [OK] INV-1 帧 1823x1000 == 窗口 rect")
    bus.log("  [OK] INV-13 内容 均值RGB=(58, 61, 66) 色彩=38")
    bus.log("  [警告] 退出通知资产未采集 —— 无法判定「正常完成」")
    # 停在这里，留时间给外部截图
    bus.log("\n[GUI 自检] 保持 running 状态 %d 秒，供截图" % HOLD_SECONDS)
    time.sleep(HOLD_SECONDS)
    bus.node(6, "", "done")
    bus.finished(0, "自检完成")


def main():
    app = App(dry_run=True)
    app.title("ok-ww 黑盒编排 — GUI 骨架（自检中）")
    # 用假 worker 替换真编排
    import orchestrator.gui as g
    g.run_orchestrator = fake_worker
    app.worker = None

    app.after(300, app.on_run)          # 起来就自动跑
    app.after(int((HOLD_SECONDS + 3) * 1000), app.destroy)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
