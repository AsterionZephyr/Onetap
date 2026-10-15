"""逐节点实机巡游：启动真 GUI，模拟真实操作，记录每个动作的成败。

与 _probe_gui2_selftest.py 的区别：那个是**无头断言**，这个是**真开窗口、真点**，
并把每一步的实测结果（成功/异常/超时）打印出来，用于定位「故障发生在哪个节点」。

只读驱动，不改仓库任何文件（除本脚本自身与日志）。
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

RESULTS = []


def rec(node, action, ok, detail=""):
    RESULTS.append((node, action, ok, detail))
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {node:<10} {action:<28} {detail}", flush=True)


def main():
    print("=" * 74)
    print("逐节点实机巡游")
    print("=" * 74)

    # ---- 节点 A：导入 GUI ----
    try:
        from gui import app as app_mod
        rec("A.import", "import gui.app", True)
    except Exception as e:
        rec("A.import", "import gui.app", False, repr(e))
        traceback.print_exc()
        return 1

    # ---- 节点 B：构造 App（会真开窗）----
    try:
        a = app_mod.App()
        a.update()
        rec("B.construct", "App() + update()", True,
            f"window={a.winfo_width()}x{a.winfo_height()}")
    except Exception as e:
        rec("B.construct", "App() + update()", False, repr(e))
        traceback.print_exc()
        return 1

    try:
        # ---- 节点 C：Notebook 结构 ----
        try:
            nb = a.nb
            tabs = nb.tabs()
            rec("C.notebook", "tab count", len(tabs) == 2, f"{len(tabs)} tabs")
            rec("C.notebook", "selected index", nb.index(nb.select()) == 0,
                f"index={nb.index(nb.select())}")
            b0 = nb.bbox(0)
            b1 = nb.bbox(1)
            rec("C.notebook", "bbox(0)", b0 is not None and b0[2] > 0, str(b0))
            rec("C.notebook", "bbox(1)", b1 is not None and b1[2] > 0, str(b1))
        except Exception as e:
            rec("C.notebook", "inspect", False, repr(e))
            traceback.print_exc()

        # ---- 节点 D：切页（程序化，等价于点 tab）----
        try:
            nb.select(1)
            a.update()
            sel = nb.index(nb.select())
            rec("D.switch", "select(1) -> 节点代码页", sel == 1, f"selected={sel}")
        except Exception as e:
            rec("D.switch", "select(1)", False, repr(e))
            traceback.print_exc()

        try:
            nb.select(0)
            a.update()
            sel = nb.index(nb.select())
            rec("D.switch", "select(0) -> 运行页", sel == 0, f"selected={sel}")
        except Exception as e:
            rec("D.switch", "select(0)", False, repr(e))
            traceback.print_exc()

        # ---- 节点 E：第 2 页点选节点载入代码 ----
        for sid in ("1", "6", "8", "9"):
            try:
                a.on_pick(sid)
                a.update()
                path = getattr(a.editor, "path", None)
                n = a.editor.line_count()
                ok = bool(path) and n > 0
                rec("E.pick", f"pick {sid} -> load", ok,
                    f"{os.path.basename(path) if path else None} {n} lines")
            except Exception as e:
                rec("E.pick", f"pick {sid}", False, repr(e))
                traceback.print_exc()

        # ---- 节点 F：保存按钮状态 ----
        try:
            a._refresh_save_buttons()
            a.update()
            rec("F.savebtn", "_refresh_save_buttons", True)
        except Exception as e:
            rec("F.savebtn", "_refresh_save_buttons", False, repr(e))
            traceback.print_exc()

        # ---- 节点 G：运行中禁止保存的守卫 ----
        try:
            a.runner.is_running = lambda: True
            import tkinter.messagebox as mb
            orig = mb.showwarning
            calls = []
            mb.showwarning = lambda *x, **k: calls.append(x)
            a.on_save()
            mb.showwarning = orig
            rec("G.guard", "on_save blocked while running", len(calls) == 1,
                f"warnings={len(calls)}")
        except Exception as e:
            rec("G.guard", "on_save guard", False, repr(e))
            traceback.print_exc()

        # ---- 节点 H：日志与节点行渲染 ----
        try:
            a.append_log("[节点 6] 测试行", "node")
            a.append_log("[OK] 测试行", "ok")
            a.append_log("[警告] 测试行", "warn")
            a.append_log("[中止] 测试行", "err")
            a.update()
            n = len(a.log_text.get("1.0", "end").strip().splitlines())
            rec("H.log", "append 4 kinds", n >= 4, f"{n} lines")
        except Exception as e:
            rec("H.log", "append_log", False, repr(e))
            traceback.print_exc()

        for st in ("running", "ok", "failed", "timeout", "skipped", None):
            try:
                a.set_node("6", "抓首帧并校验", st, note=None)
                a.update()
                rec("H.node", f"set_node {st}", True)
            except Exception as e:
                rec("H.node", f"set_node {st}", False, repr(e))
                traceback.print_exc()

        try:
            a.set_current("6", "抓首帧并校验", "running")
            a.update()
            rec("H.current", "set_current", True)
        except Exception as e:
            rec("H.current", "set_current", False, repr(e))
            traceback.print_exc()

        # ---- 节点 I：状态栏 ----
        try:
            a.status("测试状态", "info")
            a.update()
            rec("I.status", "status()", True)
        except Exception as e:
            rec("I.status", "status()", False, repr(e))
            traceback.print_exc()

        # ---- 节点 J：_pump 泵（含未运行时）----
        try:
            a._pump()
            a.update()
            rec("J.pump", "_pump idle", True)
        except Exception as e:
            rec("J.pump", "_pump idle", False, repr(e))
            traceback.print_exc()

        # ---- 节点 K：_check_chain ----
        try:
            a._check_chain()
            rec("K.chain", "_check_chain", True)
        except Exception as e:
            rec("K.chain", "_check_chain", False, repr(e))
            traceback.print_exc()

        # ---- 节点 L：关闭 ----
        try:
            a.destroy()
            rec("L.close", "destroy", True)
        except Exception as e:
            rec("L.close", "destroy", False, repr(e))
            traceback.print_exc()

    finally:
        try:
            a.destroy()
        except Exception:
            pass

    print("=" * 74)
    fails = [r for r in RESULTS if not r[2]]
    print(f"合计 {len(RESULTS)} 项，失败 {len(fails)} 项")
    for node, action, _ok, detail in fails:
        print(f"  ✖ {node} :: {action} :: {detail}")
    print("=" * 74)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
