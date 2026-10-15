"""_probe_gui_target_wire.py — 验证 GUI 的目标选择器**真的**把 --target 送出去了

为什么要这个探针（而不是靠人肉点击复核）：

    Tk 窗口在**远程会话**（GameViewer）下收不到合成点击 —— `desktop_click`
    报告「落点与目标一致」，但按钮毫无反应。于是「GUI 能跑 both」这件事
    没法靠点击来证明。本探针改用 **Tk 自己的 API** 驱动同一条代码路径：
    直接调 `App.on_run()`，把 `Runner` stub 掉，看它到底拼出了什么 argv。

    这验证的是**真实的 on_run**（不是复刻一段逻辑），所以如果 on_run 漏传了
    --target，这里必然失败。

跑法（在仓库根）：
    python -X utf8 probe/_probe_gui_target_wire.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk                                            # noqa: E402

from gui import app as A                                        # noqa: E402


class RunnerStub:
    """替掉真 Runner：只记录 argv，不起子进程。"""

    def __init__(self):
        self.calls = []

    def is_running(self):
        return False

    def start(self, python, args):
        self.calls.append((python, list(args)))


class WatcherStub:
    def set_run_dir(self, _d):
        pass


def build_app(root):
    """造一个够用的 App 外壳：只保留 on_run 需要的属性。

    不用真的 App(...)：那会建整套界面 + 起 StateWatcher 线程，
    对「on_run 拼了什么 argv」这个命题是噪声。
    """
    a = A.App.__new__(A.App)
    a.dry_run = tk.BooleanVar(value=False)
    a.only_var = tk.StringVar(value="")
    a.resume_var = tk.BooleanVar(value=False)
    a.target_var = tk.StringVar(value=A.TARGET_CHOICES[0])
    a.python_var = tk.StringVar(value=sys.executable)
    a.editor = type("E", (), {"is_dirty": lambda self: False})()
    a.selected = None
    a.runner = RunnerStub()
    a.watcher = WatcherStub()
    a.log_text = tk.Text(root)
    a._last_status = {}
    a.node_rows = {}
    a.status = lambda *a_, **k_: None
    a._paint = lambda *a_, **k_: None
    a.set_current = lambda *a_, **k_: None

    class FakeBtn:
        def config(self, **_k):
            pass

    a.btn_run = FakeBtn()
    a.btn_stop = FakeBtn()
    a.run_dir = None
    # on_run 末尾会起 worker 线程读 stdout —— stub 掉，避免真去碰 proc
    a._work = lambda: None
    return a


def main():
    root = tk.Tk()
    root.withdraw()

    fail = []

    print("=" * 74)
    print("GUI 目标选择器 -> --target 接线验证（用真实 on_run）")
    print("=" * 74)

    # --- 1. 四个下拉项各自的 argv -------------------------------------
    print("\n1. 逐项调 on_run，看真实 argv")
    expect = {
        "跟随记录（默认）": [],
        "ok-ww": ["--target", "ww"],
        "ok-nte": ["--target", "nte"],
        "两个都跑（先 ok-ww 后 ok-nte）": ["--target", "both"],
    }
    for label in A.TARGET_CHOICES:
        a = build_app(root)
        a.target_var.set(label)
        a.on_run()
        got = a.runner.calls[-1][1] if a.runner.calls else None
        want = expect[label]
        ok = got == want
        if not ok:
            fail.append(f"{label}: 期望 {want}，实得 {got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] {label:36s} -> {got}")

    # --- 2. dry-run 与「只跑节点」能叠加 -------------------------------
    print("\n2. 与 dry-run / 只跑节点 叠加")
    a = build_app(root)
    a.target_var.set("两个都跑（先 ok-ww 后 ok-nte）")
    a.dry_run.set(True)
    a.only_var.set("1")
    a.on_run()
    got = a.runner.calls[-1][1]
    # 顺序：--dry-run, --only 1, --target both
    want = ["--dry-run", "--only", "1", "--target", "both"]
    ok = got == want
    if not ok:
        fail.append(f"叠加：期望 {want}，实得 {got}")
    print(f"  [{'OK ' if ok else 'FAIL'}] dry-run + 只跑 1 + both -> {got}")

    # --- 3. 关键：跟随记录**不能**传 ww --------------------------------
    # 这是本次改动最容易写错的地方：写成 args += ["--target", "ww"] 的话，
    # 「接着上次」续跑 ok-nte 会被悄悄改回 ok-ww。
    print("\n3. 守卫：『跟随记录』不得传 --target")
    a = build_app(root)
    a.target_var.set("跟随记录（默认）")
    a.resume_var.set(True)
    a.on_run()
    got = a.runner.calls[-1][1]
    ok = "--target" not in got
    if not ok:
        fail.append(f"跟随记录传了 --target：{got}")
    print(f"  [{'OK ' if ok else 'FAIL'}] 接着上次 + 跟随记录 -> {got}")

    # --- 4. 映射表与下拉项一一对应 -------------------------------------
    print("\n4. TARGET_CHOICES 与 TARGET_ARG 一一对应")
    missing = [c for c in A.TARGET_CHOICES if c not in A.TARGET_ARG]
    extra = [k for k in A.TARGET_ARG if k not in A.TARGET_CHOICES]
    ok = not missing and not extra
    if not ok:
        fail.append(f"映射表不齐：缺 {missing} 多 {extra}")
    print(f"  [{'OK ' if ok else 'FAIL'}] choices={len(A.TARGET_CHOICES)} "
          f"arg={len(A.TARGET_ARG)} 缺={missing} 多={extra}")

    root.destroy()

    print("\n" + "=" * 74)
    if fail:
        print(f"失败 {len(fail)} 项：")
        for f in fail:
            print(f"  - {f}")
        return 1
    print("全部通过 —— GUI 的 on_run 确实把 --target 送上去了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
