"""docs/_probe_gui2_sec5.py — 只跑自检的第 5 节，带分步计时，定位卡在哪一步"""

import os
import sys
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.app import App          # noqa: E402
from gui.editor import CodeEditor  # noqa: E402


def step(label, fn):
    t0 = time.perf_counter()
    r = fn()
    print(f"  {label:38s} {(time.perf_counter() - t0) * 1000:9.1f} ms", flush=True)
    return r


app = App(dry_run=True)
app.withdraw()
app.update()
print("App built", flush=True)

ed = step("CodeEditor(app)", lambda: CodeEditor(app))
big = "\n".join(f"def f{i}(x):  # c{i}\n    return \"s{i}\" + str(x) * {i}"
                for i in range(400))
step("insert 800 lines", lambda: ed.text.insert("1.0", big))
step("highlight_all #1", lambda: ed.highlight_all())
step("highlight_all #2", lambda: ed.highlight_all())

full = step("collect tag_ranges x5",
            lambda: {t: sorted(str(r) for r in ed.text.tag_ranges(t))
                     for t in ("kw", "str", "comment", "num", "def")})

step("tag_remove x5",
     lambda: [ed.text.tag_remove(t, "1.0", "end")
              for t in ("kw", "str", "comment", "num", "def")])
step("highlight_range(1,1)", lambda: ed.highlight_range(1, 1))

print("\nnow pumping the App event loop for 2s to see if it settles...", flush=True)
t0 = time.perf_counter()
while time.perf_counter() - t0 < 2:
    app.update()
print("pumped OK", flush=True)

app.destroy()
print("DONE")
