"""docs/_probe_gui2_visual.py — 打开真窗口，停在一个可截屏的状态

依项目自身原则「抓图必须落盘供肉眼复核」（HANDOFF §10.5），GUI 也必须**看图**
判断。本脚本开窗、填一些假日志与节点状态、切到第 2 页载入一个节点，
然后**保持窗口存活 N 秒**供外部截屏。

跑法：
    & "D:\\WORKs\\Anaconda\\python.exe" -X utf8 docs\\_probe_gui2_visual.py [秒数]
"""

import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.app import App  # noqa: E402

HOLD = int(sys.argv[1]) if len(sys.argv) > 1 else 25

app = App(dry_run=True)
app.geometry("1280x780+60+40")
app.update()

# --- 造一个"跑到节点 6"的现场 -------------------------------------------------
app.append_log("[主控] 启动节点 1 check_admin")
app.append_log("  [跳过] --skip-admin-check 已指定 —— 后续不会执行任何清理")
app.append_log("[节点 1] -> SKIPPED   按参数跳过")
app.append_log("[主控] 启动节点 2 launch")
app.append_log("  已启动 E:\\TOOLS\\ScriptsGames\\ok-ww\\ok-ww.exe")
app.append_log("[节点 2] -> OK   已启动 ok-ww.exe")
app.append_log("[主控] 启动节点 4 wait_second_layer")
app.append_log("  等待第二层 Qt 窗口…")
app.append_log("[节点 4] -> OK   第二层就绪 hwnd=32966438")
app.append_log("[主控] 启动节点 5 wait_ready")
app.append_log("[节点 5] -> OK   就绪 1458x800")
app.append_log("[主控] 启动节点 6 first_frame")
app.append_log("[节点 6] first_frame   （run-dir ...\\run-20261006-014118）")
app.append_log("  [OK] INV-1 帧 1458x800 == 窗口 rect")
app.append_log("  [OK] INV-13 内容 均值RGB=[49, 48, 48] 色彩=39")
app.append_log("  [身份校验] 侧栏图标位置/分数")
app.append_log("  [警告] 身份校验失败：侧栏图标 score=0.4074 < 0.95")
app.append_log("  [INV-12] 身份校验失败：帧可能不是 ok-ww")
app.append_log("[节点 6] -> FAILED   身份校验失败（帧可能不是 ok-ww）")

for sid, st in (("1", "skipped"), ("2", "ok"), ("4", "ok"),
                ("5", "ok"), ("6", "failed")):
    app.set_node(sid, st, {"skipped": "按参数跳过", "ok": "已完成",
                           "failed": "身份校验失败"}[st])
app.set_current("6", "抓首帧并校验", "failed")
app.status("演示状态：节点 6 失败，可切到「节点代码」页修 step6", "err")

# --- 第 2 页也准备好，但**先显示第 1 页** --------------------------------------
app.on_pick("6")
app.update()

# 用 after 自动切到第 2 页，避免依赖合成点击（远程会话可能覆盖光标）
SHOW_PAGE2_AT = max(4, HOLD // 3)
app.after(SHOW_PAGE2_AT * 1000, lambda: app.nb.select(app.page_code))
app.after(HOLD * 1000, app.destroy)

print(f"窗口已打开，保持 {HOLD} 秒供截屏。", flush=True)
print(f"  前 {SHOW_PAGE2_AT}s 显示第 1 页（运行），之后切到第 2 页（节点代码）",
      flush=True)
app.mainloop()
print("DONE")
