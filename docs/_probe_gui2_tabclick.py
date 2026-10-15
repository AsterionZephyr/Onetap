"""真窗口 + 真鼠标点击：验证 Notebook 页签切换是否可用。

这个探针**开真窗口**，等它完全映射后取 bbox，打印精确屏幕坐标，
然后用真实光标（desktop_click 由外层注入）或直接 event_generate 验证。

模式 A（默认）：只打印坐标，供外层用 desktop_click 点。
模式 B：用 event_generate 模拟点击（不做真实光标，验证 widget 绑定）。
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from gui import app as app_mod


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "coords"
    a = app_mod.App()
    a.geometry("1280x780+80+80")
    a.update()
    a.deiconify()
    a.lift()
    a.attributes("-topmost", True)
    deadline = time.time() + 5
    while time.time() < deadline:
        a.update()
        time.sleep(0.05)

    nb = a.nb
    print("win  rootxy =", a.winfo_rootx(), a.winfo_rooty())
    print("nb   rootxy =", nb.winfo_rootx(), nb.winfo_rooty())
    print("nb   wh     =", nb.winfo_width(), nb.winfo_height())
    print("mapped      =", nb.winfo_ismapped())

    for i in range(2):
        bb = nb.bbox(i)
        print(f"bbox({i}) = {bb}")
        if bb and bb[2] > 0:
            x = nb.winfo_rootx() + bb[0] + bb[2] // 2
            y = nb.winfo_rooty() + bb[1] + bb[3] // 2
            print(f"  -> 屏幕物理坐标 ({x},{y})")

    if mode == "click":
        # 用真实光标位置驱动：把窗口放到已知位置，然后让外层点
        print("READY 窗口已置顶并置前，等待外层 desktop_click")
        print("SELECTED_BEFORE =", nb.index(nb.select()))
        for _ in range(120):
            a.update()
            time.sleep(0.05)
            print("SELECTED_NOW =", nb.index(nb.select()))
        a.destroy()
        return

    if mode == "generate":
        for i in (1, 0):
            nb.event_generate("<Button-1>", x=0, y=0)
            a.update()
            print("after event_generate ->", nb.index(nb.select()))

    a.destroy()


if __name__ == "__main__":
    main()
