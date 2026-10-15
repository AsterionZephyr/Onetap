"""实测：tkinter 能否写出「带行号 + 语法高亮 + 保存 + 撤销」的代码编辑器。

本文件是一次**可行性实测**，不是最终实现。目的：把"tkinter 做编辑器又丑又别扭"
这个断言变成可测量的数字（行数 / 是否需要第三方依赖 / 功能是否齐全）。

运行：python docs/_probe_tk_editor.py
"""

import keyword
import os
import re
import sys
import time
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox

PY_KEYWORDS = set(keyword.kwlist) | {"self", "cls", "None", "True", "False"}
NUM_RE = re.compile(r"\b\d+(\.\d+)?\b")
STR_RE = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")
COMMENT_RE = re.compile(r"#[^\n]*")
DEF_RE = re.compile(r"\b(def|class)\s+(\w+)")


class CodeEditor(tk.Frame):
    """一个可用的 Python 代码编辑器：行号槽 + 高亮 + 撤销 + 保存。"""

    def __init__(self, master, path=None, **kw):
        super().__init__(master, **kw)
        self.path = path

        # 行号槽：一个只读 Text，宽度按行数自适应
        self.gutter = tk.Text(self, width=4, padx=4, takefocus=0,
                              border=0, background="#f0f0f0",
                              foreground="#808080", state="disabled",
                              wrap="none", cursor="arrow")
        self.gutter.pack(side="left", fill="y")

        # 主编辑区：undo=True 就自带撤销栈
        self.text = tk.Text(self, undo=True, maxundo=-1,
                            wrap="none", tabs=("4c",),
                            insertwidth=2, font=("Consolas", 11),
                            selectbackground="#cce8ff")
        self.text.pack(side="left", fill="both", expand=True)

        vs = ttk.Scrollbar(self, orient="vertical",
                           command=self._on_scroll)
        vs.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=self._sync_scroll)
        self._vs = vs

        self._setup_tags()
        self._bind_events()

        if path and os.path.isfile(path):
            self.load(path)
        else:
            self._renumber()
            self.highlight()

    # --- 高亮 ---------------------------------------------------------

    def _setup_tags(self):
        cfg = {
            "kw":      {"foreground": "#0000cc", "font": ("Consolas", 11, "bold")},
            "str":     {"foreground": "#a31515"},
            "comment": {"foreground": "#008000", "font": ("Consolas", 11, "italic")},
            "num":     {"foreground": "#098658"},
            "def":     {"foreground": "#795e26", "font": ("Consolas", 11, "bold")},
            "curline": {"background": "#f5f5f5"},
        }
        for name, opts in cfg.items():
            self.text.tag_configure(name, **opts)
        self.text.tag_configure("curline", background="#f5f5f5")
        self.text.tag_lower("curline")

    def highlight(self, *_):
        """全量重新高亮。

        做法：先把所有高亮 tag 摘掉，再用正则打回去。
        这是最朴素的做法；单文件几百行实测耗时可接受（见 __main__ 的计时）。
        """
        t = self.text
        for tag in ("kw", "str", "comment", "num", "def"):
            t.tag_remove(tag, "1.0", "end")
        src = t.get("1.0", "end-1c")

        # 注释优先级最高：先打注释，再打字符串，避免注释里的引号误判
        for m in COMMENT_RE.finditer(src):
            t.tag_add("comment", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in STR_RE.finditer(src):
            t.tag_add("str", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in DEF_RE.finditer(src):
            t.tag_add("def", f"1.0+{m.start(2)}c", f"1.0+{m.end(2)}c")
        for m in NUM_RE.finditer(src):
            t.tag_add("num", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in re.finditer(r"\b\w+\b", src):
            if m.group(0) in PY_KEYWORDS:
                t.tag_add("kw", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def _mark_curline(self, *_):
        self.text.tag_remove("curline", "1.0", "end")
        self.text.tag_add("curline", "insert linestart", "insert lineend+1c")

    # --- 行号 ---------------------------------------------------------

    def _renumber(self):
        lines = int(self.text.index("end-1c").split(".")[0])
        self.gutter.configure(state="normal")
        self.gutter.delete("1.0", "end")
        self.gutter.insert("1.0", "\n".join(str(i) for i in range(1, lines + 1)))
        self.gutter.configure(state="disabled", width=max(3, len(str(lines)) + 1))

    def _sync_scroll(self, first, last):
        self._vs.set(first, last)
        self.gutter.yview_moveto(first)

    def _on_scroll(self, *args):
        self.text.yview(*args)
        self.gutter.yview(*args)

    # --- 事件 ---------------------------------------------------------

    def _bind_events(self):
        t = self.text
        t.bind("<<Modified>>", self._on_modified)
        t.bind("<KeyRelease>", self._on_key)
        t.bind("<ButtonRelease-1>", self._on_key)
        t.bind("<Tab>", self._on_tab)
        t.bind("<Return>", self._on_return)
        t.bind("<Control-s>", lambda e: (self.save(), "break")[1])

    def _on_modified(self, _):
        self._renumber()
        self.text.edit_modified(False)

    def _on_key(self, event=None):
        self.highlight()
        self._mark_curline()

    def _on_tab(self, _):
        self.text.insert("insert", "    ")
        return "break"

    def _on_return(self, event=None):
        """回车自动保持上一行缩进 —— 没有这个就不像编辑器。"""
        line = self.text.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        if line.rstrip().endswith(":"):
            indent += "    "
        self.text.insert("insert", "\n" + indent)
        return "break"

    # --- 文件 ---------------------------------------------------------

    def load(self, path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", f.read())
        self.path = path
        self.text.edit_reset()          # 清空撤销栈
        self.text.edit_modified(False)
        self._renumber()
        self.highlight()

    def save(self, path=None):
        path = path or self.path
        if not path:
            path = filedialog.asksaveasfilename(defaultextension=".py")
            if not path:
                return False
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.text.get("1.0", "end-1c"))
        self.path = path
        self.text.edit_modified(False)
        return True


def _selftest():
    """无头自检：验证核心功能真的работает，不依赖人眼看窗口。"""
    root = tk.Tk()
    root.withdraw()
    ed = CodeEditor(root)

    src = (
        "import os\n"
        "\n"
        "def hello(name):\n"
        "    # greet\n"
        "    msg = \"hi \" + name\n"
        "    return msg * 42\n"
    )
    ed.text.insert("1.0", src)

    t0 = time.perf_counter()
    ed.highlight()
    dt = (time.perf_counter() - t0) * 1000

    print("=== tkinter 代码编辑器自检 ===")
    print(f"1. 高亮 6 行源码耗时           : {dt:.2f} ms")

    counts = {tag: len(ed.text.tag_ranges(tag)) // 2
              for tag in ("kw", "str", "comment", "num", "def")}
    print(f"2. 各类高亮命中数              : {counts}")
    assert counts["kw"] > 0, "关键字未高亮"
    assert counts["str"] > 0, "字符串未高亮"
    assert counts["comment"] > 0, "注释未高亮"
    assert counts["def"] > 0, "def 名未高亮"

    # 行号槽应覆盖 Text 报告的全部行。注意：以 \n 结尾的源码在 Text 里
    # 会多出最后一空行，故 6 行源码 → 7 行槽位，这是正确行为。
    ed._renumber()
    gutter = ed.gutter.get("1.0", "end-1c")
    nlines = int(ed.text.index("end-1c").split(".")[0])
    print(f"3. 行号槽行数                  : {len(gutter.splitlines())} "
          f"(Text 报告 {nlines} 行)  内容={gutter!r}")
    assert len(gutter.splitlines()) == nlines, "行号槽与正文行数不一致"
    assert gutter.splitlines()[0] == "1", "行号未从 1 开始"

    # 撤销：Text(undo=True) 自带栈，但**必须**自己插 separator，
    # 否则连续的 insert 会被合并成一个 undo 组（实测：两次 insert 一次 undo 全没）。
    before = ed.text.get("1.0", "end-1c")
    ed.text.edit_separator()
    ed.text.insert("end", "x = 1\n")
    ed.text.edit_separator()
    ed.text.edit_undo()
    after = ed.text.get("1.0", "end-1c")
    print(f"4. 撤销可用 (undo=True)        : {before == after}")
    assert before == after, "撤销失效"

    # 自动缩进：把光标放到刚插入的 "if True:" 行尾，回车应缩进一级
    ed.text.insert("end", "\n")
    end_line = int(ed.text.index("end-1c").split(".")[0])
    ed.text.insert("end", "if True:")
    ed.text.mark_set("insert", f"{end_line}.end")
    ed._on_return()
    next_line = ed.text.get(f"{end_line + 1}.0", f"{end_line + 1}.end")
    print(f"5. 回车自动缩进                : {next_line!r}")
    assert next_line.startswith("    "), "自动缩进未生效"

    # 保存往返
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_tmp.py")
    ed.save(tmp)
    with open(tmp, "r", encoding="utf-8") as f:
        roundtrip = f.read()
    os.remove(tmp)
    print(f"6. 保存往返一致                : {roundtrip == ed.text.get('1.0', 'end-1c')}")
    assert roundtrip == ed.text.get("1.0", "end-1c"), "保存往返不一致"

    # 大文件性能：高亮是主要成本
    big = "\n".join(f"def f{i}(x):  # c{i}\n    return \"s{i}\" + str(x) * {i}"
                    for i in range(300))
    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", big)
    t0 = time.perf_counter()
    ed.highlight()
    dt_big = (time.perf_counter() - t0) * 1000
    nlines = int(ed.text.index("end-1c").split(".")[0])
    print(f"7. 大文件 {nlines} 行高亮耗时     : {dt_big:.1f} ms  "
          f"({'每键可接受' if dt_big < 120 else '打字会卡'})")

    root.destroy()
    print("\n全部自检通过。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        root = tk.Tk()
        root.title("tkinter 代码编辑器实测")
        root.geometry("1000x600")
        ed = CodeEditor(root)
        ed.pack(fill="both", expand=True)
        bar = ttk.Frame(root)
        bar.pack(fill="x")
        ttk.Button(bar, text="打开", command=lambda: ed.load(
            filedialog.askopenfilename())).pack(side="left")
        ttk.Button(bar, text="保存", command=ed.save).pack(side="left")
        ttk.Button(bar, text="自检", command=_selftest).pack(side="left")
        if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
            ed.load(sys.argv[1])
        root.mainloop()
