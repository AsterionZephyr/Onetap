"""实测：增量高亮能否把 tkinter 编辑器拉回「打字流畅」。

上一轮实测：全量重打高亮是 O(n^2)，800 行就要 178ms/键，不可用。
本实测验证对策：**只重打改动行所在的可视区域**，并对比全量。

关键洞察：语法高亮的正确性只需在"改动点附近"保证；
远处文本的高亮保持不变即可（它本来就是对的）。
"""

import re
import sys
import time
import keyword
import tkinter as tk

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from _probe_tk_editor import CodeEditor, PY_KEYWORDS, NUM_RE, STR_RE, COMMENT_RE, DEF_RE  # noqa: E402

r = tk.Tk()
r.withdraw()
ed = CodeEditor(r)
TEXT = ed.text


def highlight_range(lo, hi):
    """只重打 [lo, hi] 行区间的高亮。"""
    for tag in ("kw", "str", "comment", "num", "def"):
        TEXT.tag_remove(tag, "%d.0" % lo, "%d.end" % hi)
    # 取区间文本，用「起始偏移」换算成 Text 索引
    base = "%d.0" % lo
    seg = TEXT.get(base, "%d.end" % hi)
    for m in COMMENT_RE.finditer(seg):
        TEXT.tag_add("comment", "%s+%dc" % (base, m.start()), "%s+%dc" % (base, m.end()))
    for m in STR_RE.finditer(seg):
        TEXT.tag_add("str", "%s+%dc" % (base, m.start()), "%s+%dc" % (base, m.end()))
    for m in DEF_RE.finditer(seg):
        TEXT.tag_add("def", "%s+%dc" % (base, m.start(2)), "%s+%dc" % (base, m.end(2)))
    for m in NUM_RE.finditer(seg):
        TEXT.tag_add("num", "%s+%dc" % (base, m.start()), "%s+%dc" % (base, m.end()))
    for m in re.finditer(r"\b\w+\b", seg):
        if m.group(0) in PY_KEYWORDS:
            TEXT.tag_add("kw", "%s+%dc" % (base, m.start()), "%s+%dc" % (base, m.end()))


def build(n):
    chunks = []
    for i in range(n):
        chunks.append("def f%d(x):  # comment %d" % (i, i))
        chunks.append('    return "s%d" + str(x) * %d' % (i, i))
    return "\n".join(chunks)


print("=== 全量 vs 增量（只重打可视区 40 行）===")
print("%-8s %-14s %-14s %s" % ("行数", "全量ms", "增量ms", "提速"))
for n in (200, 400, 800, 1200, 2000, 4000):
    src = build(n)
    TEXT.delete("1.0", "end")
    TEXT.insert("1.0", src)
    ed.highlight()

    t0 = time.perf_counter(); ed.highlight(); full = (time.perf_counter() - t0) * 1000

    # 模拟在文件中部打字后的增量重打
    mid = max(1, n // 4)
    TEXT.mark_set("insert", "%d.5" % mid)
    t0 = time.perf_counter()
    highlight_range(max(1, mid - 20), mid + 20)
    inc = (time.perf_counter() - t0) * 1000

    nlines = int(TEXT.index("end-1c").split(".")[0])
    print("%-8d %-14.1f %-14.2f %.0fx" % (nlines, full, inc, full / max(inc, 1e-6)))

# --- 正确性：增量结果是否与全量一致？ ---
print()
print("=== 正确性：增量高亮 == 全量高亮？ ===")
src = build(60)
TEXT.delete("1.0", "end")
TEXT.insert("1.0", src)

ed.highlight()
full_tags = {t: tuple(TEXT.tag_ranges(t)) for t in ("kw", "str", "comment", "num", "def")}

for t in ("kw", "str", "comment", "num", "def"):
    TEXT.tag_remove(t, "1.0", "end")
highlight_range(1, 200)
inc_tags = {t: tuple(TEXT.tag_ranges(t)) for t in ("kw", "str", "comment", "num", "def")}

same = full_tags == inc_tags
print("  一致:", same)
if not same:
    for t in full_tags:
        if full_tags[t] != inc_tags[t]:
            print("   差异 tag=%s 全量%d 段 / 增量%d 段"
                  % (t, len(full_tags[t]) // 2, len(inc_tags[t]) // 2))

r.destroy()
