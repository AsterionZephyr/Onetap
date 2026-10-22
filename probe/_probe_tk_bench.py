"""实测：tkinter 全量重打高亮的成本随文件规模的增长。

这是决定"tkinter 能不能当代码编辑器用"的关键数字：
如果每次按键都要几十~上百毫秒，打字就会发涩。
"""

import sys
import time
import tkinter as tk

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from _probe_tk_editor import CodeEditor  # noqa: E402

r = tk.Tk()
r.withdraw()
ed = CodeEditor(r)

print("=== 全量重打高亮的成本 vs 文件规模 ===")
print("%-8s %-10s %-12s %s" % ("行数", "字符数", "全量高亮ms", "判定"))

for n in (50, 100, 200, 400, 600, 1000, 2000):
    chunks = []
    for i in range(n):
        chunks.append("def f%d(x):  # comment %d" % (i, i))
        chunks.append('    return "s%d" + str(x) * %d' % (i, i))
    src = "\n".join(chunks)

    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", src)
    ed.highlight()                                    # 预热
    t0 = time.perf_counter()
    ed.highlight()
    dt = (time.perf_counter() - t0) * 1000
    nlines = int(ed.text.index("end-1c").split(".")[0])
    verdict = ("流畅" if dt < 16 else
               "可接受" if dt < 60 else
               "打字发涩" if dt < 150 else "不可用")
    print("%-8d %-10d %-12.1f %s" % (nlines, len(src), dt, verdict))

# --- 增量高亮的设想：只重打「改动行附近」 ---
print()
print("=== 若只重打光标所在行附近（增量策略）===")
n = 1000
chunks = []
for i in range(n):
    chunks.append("def f%d(x):  # comment %d" % (i, i))
    chunks.append('    return "s%d" + str(x) * %d' % (i, i))
src = "\n".join(chunks)
ed.text.delete("1.0", "end")
ed.text.insert("1.0", src)
ed.highlight()

t0 = time.perf_counter()
# 只处理光标行上下各 2 行
cur = int(ed.text.index("insert").split(".")[0])
lo, hi = max(1, cur - 2), cur + 2
for tag in ("kw", "str", "comment", "num", "def"):
    ed.text.tag_remove(tag, "%d.0" % lo, "%d.end" % hi)
seg = ed.text.get("%d.0" % lo, "%d.end" % hi)
import re
for m in re.finditer(r"\b\w+\b", seg):
    pass
dt = (time.perf_counter() - t0) * 1000
print("  取 5 行文本 + 清 tag 耗时 : %.2f ms  (对比全量 %.1f ms)" % (dt, 0.0))
r.destroy()
