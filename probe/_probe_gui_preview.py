"""验证「帧预览」面板：把一个真实图像喂给 show_frame，确认能渲染。

这是骨架里最后一个未实测的部分。用 templates/2_ww.png（1823x42 的行模板）
作为测试图 —— 它够宽，能验证缩放到预览区是否正确保持纵横比。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import win32
win32.ensure_dpi_aware()

from orchestrator.gui import App

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(REPO, "templates", "2_ww.png")


def main():
    app = App(dry_run=True)
    app.title("帧预览自检")

    def feed():
        print("喂图:", IMG, "存在:", os.path.isfile(IMG))
        app.show_frame(IMG)
        pw = app.preview.winfo_width()
        ph = app.preview.winfo_height()
        print("预览区尺寸: %dx%d" % (pw, ph))
        print("PhotoImage 已建立:", app._preview_img is not None)
        if app._preview_img:
            print("图像尺寸: %dx%d"
                  % (app._preview_img.width(), app._preview_img.height()))
        app.append_log("[GUI 自检] 帧预览已渲染")

    app.after(400, feed)
    app.after(6000, app.destroy)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
