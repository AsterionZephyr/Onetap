"""_probe_gui_target_wire.py — 验证 GUI 的目标选择器**真的**把 --target 送出去了

为什么要这个探针（而不是靠人肉点击复核）：

    Tk 窗口在**远程会话**（GameViewer）下收不到合成点击 —— `desktop_click`
    报告「落点与目标一致」，但按钮毫无反应。于是「GUI 能把选中的程序跑起来」
    这件事没法靠点击来证明。本探针改用 **Tk 自己的 API** 驱动同一条代码路径：
    直接调 `App.on_run()`，把 `Runner` stub 掉，看它到底拼出了什么 argv。

    这验证的是**真实的 on_run**（不是复刻一段逻辑），所以如果 on_run 漏传了
    --target、或者把「未勾选」当成「跟随记录」，这里必然失败。

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
    a.dry_run = tk.BooleanVar(master=root, value=False)
    a.only_var = tk.StringVar(master=root, value="")
    a.resume_var = tk.BooleanVar(master=root, value=False)
    a.follow_var = tk.BooleanVar(master=root, value=True)
    a.target_vars = {k: tk.BooleanVar(master=root, value=True)
                     for k, _d in A.TARGET_PROGRAMS}
    # --- 执行顺序 ---------------------------------------------------------
    # 2026-10-23 起顺序**可变**（GUI 的 ↑/↓ 改的就是它），App 用 self._order
    # 保存当前顺序。这里必须显式给初值：App.__new__ 没跑 tk.Tk.__init__，
    # 没设过的属性会落到 tkinter 的 __getattr__ 上无限递归（不是 AttributeError）。
    a._order = [k for k, _d in A.TARGET_PROGRAMS]
    a.python_var = tk.StringVar(master=root, value=sys.executable)
    a.editor = type("E", (), {"is_dirty": lambda self: False})()
    a.selected = None
    a.runner = RunnerStub()
    a.watcher = WatcherStub()
    a.log_text = tk.Text(root)
    a._tstate = {}
    a._active_target = None
    a._view_target = None
    a.node_rows = {}
    a.status = lambda *a_, **k_: None
    a._paint = lambda *a_, **k_: None
    a.set_current = lambda *a_, **k_: None
    a._set_target_controls = lambda *a_, **k_: None
    a._repaint_steps = lambda *a_, **k_: None
    # on_run 末尾会 _sync_scope() 重建两页的节点行 —— 对「拼了什么 argv」是噪声，
    # 而 stub 外壳里没有 run_list 等控件：_sync_scope 的 hasattr(self, "run_list")
    # 会落到 tkinter 的 __getattr__ 上无限递归。故只在这里 stub 掉画面同步。
    a._sync_scope = lambda *a_, **k_: None
    a._refresh_target_dots = lambda *a_, **k_: None

    class FakeBtn:
        def config(self, **_k):
            pass

    class FakeLabel(FakeBtn):
        pass

    a.lbl_pick = FakeLabel()
    a.lbl_targets = FakeLabel()
    # `App.__new__` 没跑 tk.Tk.__init__，**没设过的属性**会落到 tkinter 的
    # __getattr__ 上无限递归 —— 所以这些属性必须显式给值，不能靠 getattr 默认。
    a._target_rows = {}

    a.btn_run = FakeBtn()
    a.btn_stop = FakeBtn()
    a.btn_all = FakeBtn()
    a.btn_none = FakeBtn()
    a.run_dir = None
    # on_run 末尾会起 worker 线程读 stdout —— stub 掉，避免真去碰 proc
    a._work = lambda: None
    return a


def picked(a, keys):
    """把勾选状态设成 keys（其余不勾），并关掉「跟随记录」。"""
    a.follow_var.set(False)
    for k in a.target_vars:
        a.target_vars[k].set(k in keys)


def main():
    root = tk.Tk()
    root.withdraw()

    fail = []
    warnings = []

    def note(msg):
        if not msg:
            fail.append("on_run 没有起子进程")

    orig_warn = A.messagebox.showwarning

    def fake_warn(title, msg, **kw):
        warnings.append((title, msg))

    A.messagebox.showwarning = fake_warn

    print("=" * 74)
    print("GUI 目标选择器 -> --target 接线验证（用真实 on_run）")
    print(f"目标清单：{[k for k, _d in A.TARGET_PROGRAMS]}")
    print("=" * 74)

    try:
        # --- 1. 单目标 -------------------------------------------------
        print("\n1. 只勾一个 -> --target <key>")
        for key, _disp in A.TARGET_PROGRAMS:
            a = build_app(root)
            picked(a, [key])
            a.on_run()
            got = a.runner.calls[-1][1] if a.runner.calls else None
            want = ["--target", key]
            ok = got == want
            if not ok:
                fail.append(f"只勾 {key}: 期望 {want}，实得 {got}")
            print(f"  [{'OK ' if ok else 'FAIL'}] 只勾 {key:4s} -> {got}")

        # --- 2. 多目标：默认顺序 = 清单声明顺序 --------------------------
        print("\n2. 多选 -> --target a,b（默认顺序 = 清单声明顺序）")
        ks = [k for k, _d in A.TARGET_PROGRAMS]
        a = build_app(root)
        picked(a, list(reversed(ks)))          # 故意反着点
        a.on_run()
        got = a.runner.calls[-1][1]
        want = ["--target", ",".join(ks)]
        ok = got == want
        if not ok:
            fail.append(f"多选: 期望 {want}，实得 {got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 反序勾选 -> {got}")

        a = build_app(root)
        picked(a, ks)
        a.on_run()
        got = a.runner.calls[-1][1]
        need = ["--target", ",".join(ks)]
        ok = got == need
        if not ok:
            fail.append(f"全选: 期望 {need}，实得 {got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 全选 -> {got}")

        # --- 2b. 任意顺序：GUI 的 ↑/↓ 改的就是 --target 的排列 -----------
        # 用户 2026-10-23 的要求：「可以任意调整程序运行顺序」。顺序存在
        # App._order 里；这里直接把 _order 改成反序，看 on_run 是否照它拼。
        print("\n2b. 任意顺序 -> --target 按 _order 排列（不是声明序）")
        rev = list(reversed(ks))
        a = build_app(root)
        picked(a, ks)
        a._order = rev
        a.on_run()
        got = a.runner.calls[-1][1]
        want = ["--target", ",".join(rev)]
        ok = got == want
        if not ok:
            fail.append(f"反序执行: 期望 {want}，实得 {got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 改序后全选 -> {got}")

        # 只勾一部分时，顺序仍只由 _order 决定（不是勾选先后、也不是声明序）
        a = build_app(root)
        picked(a, [ks[0], ks[-1]])
        a._order = rev
        a.on_run()
        got = a.runner.calls[-1][1]
        want = ["--target", ",".join(k for k in rev if k in (ks[0], ks[-1]))]
        ok = got == want
        if not ok:
            fail.append(f"改序后部分勾选: 期望 {want}，实得 {got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 改序后只勾头尾 -> {got}")

        # --- 3. 未勾任何：拒绝启动，而不是猜一个 -------------------------
        print("\n3. 守卫：未勾选任何程序 -> 拒绝启动")
        warnings.clear()
        a = build_app(root)
        picked(a, [])
        a.on_run()
        ok = (not a.runner.calls) and warnings
        if not ok:
            fail.append(f"未勾选却启动了：{a.runner.calls}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 未勾选 -> 起了 {len(a.runner.calls)} 次，"
              f"告警 {len(warnings)} 次")

        # --- 4. 关键：跟随记录**不能**传 --target ------------------------
        # 写成 args += ["--target", "ww"] 的话，「接着上次」续跑 ok-nte
        # 会被悄悄改回 ok-ww（main.py 的 --target 是覆盖语义）。
        print("\n4. 守卫：『跟随上次记录』不得传 --target")
        a = build_app(root)
        a.follow_var.set(True)
        a.resume_var.set(True)
        a.on_run()
        got = a.runner.calls[-1][1]
        ok = "--target" not in got
        if not ok:
            fail.append(f"跟随记录传了 --target：{got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 接着上次 + 跟随记录 -> {got}")

        # --- 5. 与 dry-run / 只跑节点叠加 --------------------------------
        print("\n5. 与 dry-run / 只跑节点 叠加（顺序固定）")
        a = build_app(root)
        picked(a, ks)
        a.dry_run.set(True)
        a.only_var.set("1")
        a.on_run()
        got = a.runner.calls[-1][1]
        want = ["--dry-run", "--only", "1", "--target", ",".join(ks)]
        ok = got == want
        if not ok:
            fail.append(f"叠加：期望 {want}，实得 {got}")
        print(f"  [{'OK ' if ok else 'FAIL'}] dry-run + 只跑 1 + 全选 -> {got}")

        # --- 6. 空勾 + 跟随关 = 必须拒绝（不能退化成"跑全部"）------------
        print("\n6. 全选/清空按钮的状态机")
        a = build_app(root)
        a.on_select_all()
        got_all = a.selected_targets()
        a.on_select_none()
        got_none = a.selected_targets()
        a.follow_var.set(True)
        got_follow = a.selected_targets()
        ok = (got_all == ks and got_none == [] and got_follow == [])
        if not ok:
            fail.append(f"状态机不对：all={got_all} none={got_none} follow={got_follow}")
        print(f"  [{'OK ' if ok else 'FAIL'}] 全选={got_all} 清空={got_none} "
              f"跟随={got_follow}")
    finally:
        A.messagebox.showwarning = orig_warn
        root.destroy()

    print("\n" + "=" * 74)
    if fail:
        print(f"失败 {len(fail)} 项：")
        for f in fail:
            print(f"  - {f}")
        return 1
    print("全部通过 —— GUI 的 on_run 确实把选中的目标送上去了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
