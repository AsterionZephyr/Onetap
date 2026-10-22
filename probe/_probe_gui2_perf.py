"""probe/_probe_gui2_perf.py — 高亮性能：全量 vs 增量

单独成文件（而不是塞进 -c），因为 PowerShell 会把多行 -c 参数弄坏。

跑法：
    & "D:\\WORKs\\Anaconda\\python.exe" -X utf8 probe\\_probe_gui2_perf.py
"""

import os
import sys
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.editor import CodeEditor  # noqa: E402

TAGS = ("kw", "str", "comment", "num", "def")


def make_src(n_defs):
    return "\n".join(
        f"def f{i}(x):  # comment {i}\n    return \"s{i}\" + str(x) * {i}"
        for i in range(n_defs))


root = tk.Tk()
root.withdraw()
ed = CodeEditor(root)

print("=" * 66)
print("高亮成本：全量 vs 增量（增量只重打改动行 ±20 行）")
print("=" * 66)
print(f"{'行数':>7} {'全量':>12} {'增量':>12} {'提速':>10}")
print("-" * 66)

for n in (200, 400, 800, 2000):
    src = make_src(n // 2)
    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", src)
    nlines = ed.line_count()

    t0 = time.perf_counter()
    ed.highlight_all()
    t_full = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    ed.highlight_range(1, 1)
    t_inc = (time.perf_counter() - t0) * 1000

    speed = t_full / max(t_inc, 0.001)
    print(f"{nlines:>7} {t_full:>10.1f}ms {t_inc:>10.2f}ms {speed:>9.0f}x")

# 正确性：清空后增量重打，应与全量逐 tag 一致（比对前 21 行）
src = make_src(100)
ed.text.delete("1.0", "end")
ed.text.insert("1.0", src)
ed.highlight_all()
full = {t: sorted(str(r) for r in ed.text.tag_ranges(t)) for t in TAGS}

for t in TAGS:
    ed.text.tag_remove(t, "1.0", "end")
ed.highlight_range(1, 1)
inc = {t: sorted(str(r) for r in ed.text.tag_ranges(t)) for t in TAGS}

same = True
for t in TAGS:
    f_sub = [r for r in full[t]
             if r.split(".")[0].isdigit() and int(r.split(".")[0]) <= 21]
    if f_sub != inc[t]:
        same = False
        print(f"  差异 tag={t}\n    全量前21行={f_sub[:6]}\n    增量={inc[t][:6]}")
print("-" * 66)
print(f"增量与全量逐 tag 一致（前 21 行）: {same}")

root.destroy()
print("DONE")
sys.exit(0 if same else 1)
