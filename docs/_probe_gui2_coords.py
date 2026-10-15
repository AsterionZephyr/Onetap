"""打印 GUI 控件的精确屏幕坐标（由 Tk 自己算，不靠截图估算）。

用法：在**已经开着的** GUI 上不好注入，所以这个探针自己开一个 App，
把每个控件的 winfo_rootx/rooty 打印出来。同一份代码同一套布局，
坐标可直接用于真实光标点击。

⚠️ 窗口位置必须在启动时固定（geometry），否则坐标会随窗口位置变。
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from gui import app as app_mod


def main():
    a = app_mod.App()
    a.geometry("1280x780+40+40")
    a.update()
    a.deiconify()
    a.lift()
    for _ in range(40):
        a.update()
        time.sleep(0.05)

    print("window rootxy =", a.winfo_rootx(), a.winfo_rooty(),
          "wh =", a.winfo_width(), a.winfo_height())

    def center(w, label):
        try:
            x = w.winfo_rootx() + w.winfo_width() // 2
            y = w.winfo_rooty() + w.winfo_height() // 2
            print(f"{label:<28} ({x},{y})  wh={w.winfo_width()}x{w.winfo_height()}")
        except Exception as e:
            print(f"{label:<28} ERR {e!r}")

    # Notebook 页签
    nb = a.nb
    for i, txt in ((0, "运行"), (1, "节点代码")):
        bb = nb.bbox(i)
        print(f"tab{i} bbox={bb}")
        if bb and bb[2]:
            print(f"  tab{i} 中心屏幕坐标 "
                  f"({nb.winfo_rootx()+bb[0]+bb[2]//2},"
                  f"{nb.winfo_rooty()+bb[1]+bb[3]//2})")

    # 控制条控件
    center(a.btn_run, "btn_run")
    center(a.btn_stop, "btn_stop")

    def walk(w, depth=0):
        try:
            cls = w.winfo_class()
        except Exception:
            return
        txt = ""
        try:
            txt = w.cget("text")
        except Exception:
            pass
        if cls in ("TCheckbutton", "TCombobox") or txt:
            x = w.winfo_rootx() + w.winfo_width() // 2
            y = w.winfo_rooty() + w.winfo_height() // 2
            print(f"  {'  '*depth}{cls:<14} {txt!r:<22} ({x},{y}) "
                  f"wh={w.winfo_width()}x{w.winfo_height()}")
        for c in w.winfo_children():
            walk(c, depth + 1)

    print("--- 控件树（控制条相关）---")
    walk(a)

    # 第 1 页步骤行
    print("--- 第 1 页步骤行 ---")
    for sid, info in a.node_rows.items():
        center(info["title"], f"run row {sid} title")

    # 切到第 2 页
    nb.select(1)
    a.update()
    for _ in range(20):
        a.update()
        time.sleep(0.03)
    print("--- 第 2 页 ---")
    for sid, info in a.pick_rows.items():
        center(info["title"], f"pick row {sid} title")
    center(a.btn_save, "btn_save")
    center(a.btn_revert, "btn_revert")

    a.destroy()


if __name__ == "__main__":
    main()
