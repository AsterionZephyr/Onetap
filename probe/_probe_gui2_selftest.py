"""probe/_probe_gui2_selftest.py — 两页 GUI 的无头自检

逐项验证，全部留可复现输出。跑法：

    & "D:\\WORKs\\Anaconda\\python.exe" -X utf8 probe\\_probe_gui2_selftest.py

不弹窗、不点击、不启动 ok-ww。覆盖：

  1. 每个程序的节点清单与磁盘一致（按程序读，不再是硬编码一张表）
  2. App 无头构建 + 两页存在 + 左列确实是 1/5 weight
  3. 第 1 页：日志分级 tag、当前步骤指示
  4. 第 2 页：按 (程序, 节点号) 载入对应文件；切换程序换文件；保存往返一致
  5. 编辑器增量高亮 vs 全量高亮：逐 tag 一致 + 常数时间
  6. 运行中禁止保存的守卫
  7. 路径固定：编辑器只认**当前程序清单里**的节点文件
"""

import os
import sys
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui import chain                      # noqa: E402
from gui.app import App                    # noqa: E402
from gui.editor import CodeEditor          # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(f"  {'[OK]  ' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


def row_of(key, sid):
    return chain.node_of(key, sid)


print("=" * 74)
print("两页 GUI 无头自检")
print("=" * 74)

# ---------------------------------------------------------------- 1
print("\n1. 每个程序的节点清单与磁盘一致")
keys = chain.keys()
check("程序顺序 = programs.ALL（zmd, ww, nte）",
      keys == ["zmd", "ww", "nte"], str(keys))
problems = chain.verify_against_disk()
check("清单无漂移", not problems,
      "" if not problems else "\n     " + "\n     ".join(problems))
EXPECTED_IDS = ["1", "2", "4", "5", "6", "7", "8", "9"]
for key in keys:
    rows = chain.nodes(key)
    check(f"{key} 节点数 = 8", len(rows) == 8, f"{len(rows)} 节")
    check(f"{key} 编号沿用原编号（无 3）",
          chain.ids(key) == EXPECTED_IDS, str(chain.ids(key)))
    missing = [r[0] for r in rows
               if not os.path.isfile(chain.step_file(key, r))]
    check(f"{key} 每节的文件都存在", not missing, str(missing))
    owned = {r[0] for r in rows if not row_of(key, r[0])["shared"]}
    want = {"5", "6", "8"} if key == "zmd" else {"8"}
    check(f"{key} 专属节点 = {sorted(want)}", owned == want, str(sorted(owned)))

# ---------------------------------------------------------------- 2
print("\n2. App 无头构建")
app = App(dry_run=True)
app.withdraw()
app.update()
check("App 构建成功", True)
check("两个页面", app.nb.index("end") == 2, f"页数={app.nb.index('end')}")
scope = app._scope_key
check("初始显示范围是目标程序之一", scope in keys, str(scope))
rows = chain.nodes(scope)
check("第 1 页步骤行数 = 当前程序节点数",
      len(app.node_rows) == len(rows), f"{len(app.node_rows)}/{len(rows)}")
check("第 2 页步骤行数 = 当前程序节点数",
      len(app.pick_rows) == len(rows), f"{len(app.pick_rows)}/{len(rows)}")
check("行号与清单顺序一致", list(app.node_rows) == chain.ids(scope),
      str(list(app.node_rows)))
star_rows = [r for r in rows if r[4]]
for r in star_rows:
    txt = app.node_rows[r[0]]["title"].cget("text")
    check(f"节点 {r[0]} 有专属参数 -> ★", txt.endswith("★"), txt)
no_star = [r for r in rows if not r[4]]
for r in no_star[:2]:
    txt = app.node_rows[r[0]]["title"].cget("text")
    check(f"节点 {r[0]} 无专属参数 -> 无 ★", not txt.endswith("★"), txt)
vals = list(app.cmb_only.cget("values"))
check("「只跑节点」候选 = 当前程序编号", vals == [""] + chain.ids(scope),
      str(vals))

# 切换目标程序：行要按新程序的清单重建，同一编号可能换文件
other = next(k for k in keys if k != scope)
app.on_view_target(other)
app.update()
check("切换程序后 _scope_key 跟随", app._scope_key == other,
      f"{scope} -> {app._scope_key}")
check("切换后行按新程序清单重建",
      list(app.node_rows) == chain.ids(other), str(list(app.node_rows)))
check("切换后「只跑节点」候选也换了",
      list(app.cmb_only.cget("values")) == [""] + chain.ids(other))
# 节点 5：zmd 专属、ww/nte 共用 —— 必须落到不同文件
app._view_target = "zmd"
app._sync_scope()
app.on_pick("5")
p_zmd5 = os.path.abspath(app.editor.path)
app._view_target = "ww"
app._sync_scope()
app.on_pick("5")
p_ww5 = os.path.abspath(app.editor.path)
check("节点 5 在 zmd 是专属实现",
      p_zmd5 == os.path.abspath(chain.step_file("zmd", "5"))
      and os.sep + os.path.join("apps", "zmd", "nodes") + os.sep in p_zmd5,
      chain.rel(p_zmd5))
check("节点 5 在 ww 是共用实现",
      p_ww5 == os.path.abspath(chain.step_file("ww", "5"))
      and os.sep + os.path.join("steps", "common") + os.sep in p_ww5,
      chain.rel(p_ww5))
check("同一编号在不同程序指向不同文件", p_zmd5 != p_ww5)
# 回到 zmd 继续后面的检查
app._view_target = "zmd"
app._sync_scope()
app.update()

# 左列 weight 必须是 1，右列 4  => 1/5
w0 = app.page_run.grid_columnconfigure(0)["weight"]
w1 = app.page_run.grid_columnconfigure(1)["weight"]
check("第 1 页 左:右 = 1:4（即 1/5）", (w0, w1) == (1, 4), f"weight=({w0},{w1})")
w2 = app.page_code.grid_columnconfigure(0)["weight"]
w3 = app.page_code.grid_columnconfigure(1)["weight"]
check("第 2 页 左:右 = 1:4（即 1/5）", (w2, w3) == (1, 4), f"weight=({w2},{w3})")

# ---------------------------------------------------------------- 3
print("\n3. 第 1 页：日志与当前步骤指示")
app.append_log("[节点 6] 抓首帧并校验", None)
app.append_log("  [OK] INV-1 帧尺寸通过", None)
app.append_log("  [警告] exit_notice 缺失", None)
app.append_log("[中止] 不变量被破坏：[INV-24] ...", None)
tags = {}
for i in range(1, 5):
    # tag_ranges 只接受一个索引：用 "行.列" 取该字符上的 tag
    tags[i] = [t for t in app.log_text.tag_names(f"{i}.0")
               if t in ("node", "ok", "warn", "err", "cmd", "plain")]
check("日志分级：node/ok/warn/err",
      tags[1] == ["node"] and tags[2] == ["ok"]
      and tags[3] == ["warn"] and tags[4] == ["err"], str(tags))
app.set_current("6", "抓首帧并校验", "running")
check("顶端显示当前步骤",
      "当前步骤 6" in app.lbl_current.cget("text"),
      app.lbl_current.cget("text"))

app.set_node("6", "running", "INV-1/13/17/22 + 身份校验")
check("节点行切到 running", app.node_rows["6"]["dot"].cget("text") == "\u25b6")
app.set_node("6", "failed", "身份校验失败")
check("节点行切到 failed", app.node_rows["6"]["dot"].cget("text") == "\u2716")
check("横幅：未提权时存在",
      (not app._is_admin() and app.banner.winfo_ismapped())
      or app._is_admin(),
      f"is_admin={app._is_admin()}")

# ---------------------------------------------------------------- 4
print("\n4. 第 2 页：点选 -> 载入 -> 保存往返")
# on_pick 在"有未保存修改"时会弹 askyesno（模态）。先装桩，避免无头挂死。
import gui.app as _appmod


class _Quiet:
    def showwarning(self, *a, **k):
        return "ok"

    def showerror(self, *a, **k):
        return "ok"

    def showinfo(self, *a, **k):
        return "ok"

    def askyesno(self, *a, **k):
        return True


_real_box = _appmod.messagebox
_appmod.messagebox = _Quiet()

app.on_pick("1")
check("点选后 selected", app.selected == "1", str(app.selected))
check("载入了 step1 共用文件",
      app.editor.path
      and os.path.abspath(app.editor.path)
      == os.path.abspath(chain.step_file("zmd", "1")),
      str(app.editor.path))
check("编辑器非空", app.editor.line_count() > 10, f"{app.editor.line_count()} 行")
app.on_pick("8")
check("切到节点 8 载入 zmd 的专属 step8",
      app.editor.path
      and os.path.abspath(app.editor.path)
      == os.path.abspath(chain.step_file("zmd", "8")),
      str(app.editor.path))
check("载入的是专属目录下文件",
      os.sep + os.path.join("apps", "zmd", "nodes") + os.sep
      in os.path.abspath(app.editor.path), str(app.editor.path))
check("节点 8 文件非空", app.editor.line_count() > 10,
      f"{app.editor.line_count()} 行")

# 同一节点 8 切到 ww：必须换到 ww 的专属文件（不是 zmd 的）
zmd8 = os.path.abspath(app.editor.path)
app._view_target = "ww"
app._sync_scope()
app.on_pick("8")
ww8 = os.path.abspath(app.editor.path)
check("节点 8 在 ww 是另一份专属文件", ww8 != zmd8
      and ww8 == os.path.abspath(chain.step_file("ww", "8")),
      chain.rel(ww8))
app._view_target = "zmd"
app._sync_scope()
app.on_pick("8")

# 保存往返：改一行 -> 存到临时副本 -> 比对
orig = app.editor.text.get("1.0", "end-1c")
real_path = app.editor.path
tmp = os.path.join(HERE, "_probe_gui2_tmp.py")
app.editor.text.insert("end", "\n# selftest-marker-42\n")
app.editor._dirty = True
ok, msg = app.editor.save(tmp)
with open(tmp, "r", encoding="utf-8") as f:
    back = f.read()
saved_text = app.editor.text.get("1.0", "end-1c")
os.remove(tmp)
check("保存成功", ok, msg)
check("保存往返一致", back == saved_text)
check("保存保留了结尾换行", back.endswith("\n"))

# 注意：save(tmp) 会把 editor.path 指向 tmp。这里必须**显式切回**真实文件，
# 否则随后的 load() 会去读一个已删除的临时文件。
app.editor.path = real_path
app.editor.load(real_path)
check("重新载入后丢弃了 marker", "selftest-marker-42" not in
      app.editor.text.get("1.0", "end-1c"))
check("重新载入后不脏", not app.editor.is_dirty())
check("重新载入后内容与原文件一致",
      app.editor.text.get("1.0", "end-1c") == orig)

# ---------------------------------------------------------------- 5
print("\n5. 增量高亮 vs 全量高亮")
ed = CodeEditor(app)
big = "\n".join(f"def f{i}(x):  # c{i}\n    return \"s{i}\" + str(x) * {i}"
                for i in range(400))
ed.text.insert("1.0", big)
ed.highlight_all()
full = {t: sorted(str(r) for r in ed.text.tag_ranges(t))
        for t in ("kw", "str", "comment", "num", "def")}

t0 = time.perf_counter()
ed.highlight_all()
t_full = (time.perf_counter() - t0) * 1000

# 清掉再增量重打第 1 行 -> 应与全量一致（增量带上下文，覆盖足够）
for t in ("kw", "str", "comment", "num", "def"):
    ed.text.tag_remove(t, "1.0", "end")
t0 = time.perf_counter()
ed.highlight_range(1, 1)
t_inc = (time.perf_counter() - t0) * 1000
inc = {t: sorted(str(r) for r in ed.text.tag_ranges(t))
       for t in ("kw", "str", "comment", "num", "def")}

# 增量只重打了 1..21 行，所以只比对前 21 行内的命中
same = True
for t in full:
    f_sub = [r for r in full[t] if r.split(".")[0].isdigit()
             and int(r.split(".")[0]) <= 21]
    if f_sub != inc[t]:
        same = False
check("增量 == 全量（前 21 行）", same)
check("增量比全量快", t_inc < t_full,
      f"全量 {t_full:.1f}ms vs 增量 {t_inc:.2f}ms "
      f"({t_full / max(t_inc, 0.001):.0f}x)")
check("增量耗时可忽略", t_inc < 20, f"{t_inc:.2f}ms")

# ---------------------------------------------------------------- 6
print("\n6. 守卫：运行中禁止保存")
# ⚠️ 必须先把 messagebox 换成不弹窗的桩。on_save 在"运行中"会调
#    messagebox.showwarning —— 那是**模态对话框**，无头环境下没人点确定，
#    自检会永远挂在这里（这是第一版自检踩过的坑）。
import gui.app as app_mod


class _FakeBox:
    def __init__(self):
        self.calls = []

    def showwarning(self, title, msg):
        self.calls.append(("warning", title))
        return "ok"

    def showerror(self, title, msg):
        self.calls.append(("error", title))
        return "ok"

    def showinfo(self, title, msg):
        self.calls.append(("info", title))
        return "ok"

    def askyesno(self, title, msg):
        self.calls.append(("askyesno", title))
        return True


fake_box = _FakeBox()
real_box = app_mod.messagebox
app_mod.messagebox = fake_box


class FakeRunner:
    def is_running(self):
        return True


real = app.runner
app.runner = FakeRunner()
app.editor.text.insert("end", "\n# should-not-save\n")
app.editor._dirty = True
saved = {"n": 0}


def fake_save(*a, **k):
    saved["n"] += 1
    return True, "x"


real_editor_save = app.editor.save
app.editor.save = fake_save
app.on_save()
check("运行中 on_save 未写入", saved["n"] == 0, f"save 调用 {saved['n']} 次")
check("运行中给出了警告", any(c[0] == "warning" for c in fake_box.calls),
      str(fake_box.calls))

# 反向对照：不在运行时应当**允许**保存（否则上一条测不出东西）
app.runner = FakeRunner_stopped = type("R", (), {"is_running": lambda self: False})()
app.on_save()
check("不运行时 on_save 写入", saved["n"] == 1, f"save 调用 {saved['n']} 次")

app.runner = real
app.editor.save = real_editor_save
app_mod.messagebox = real_box
app.editor.load(app.editor.path)

# ---------------------------------------------------------------- 7
print("\n7. 路径固定：编辑器只认当前程序清单里的节点文件")
app._view_target = "ww"          # ww 的节点 6 是共用实现
app._sync_scope()
app.on_pick("6")
p = os.path.abspath(app.editor.path)
check("载入路径 == 清单算出的路径",
      p == os.path.abspath(chain.step_file("ww", "6")), chain.rel(p))
under_common = p.startswith(os.path.abspath(chain.COMMON_DIR))
under_owned = p.startswith(os.path.abspath(chain.APPS_DIR))
check("载入路径在 common/ 或 apps/ 下", under_common or under_owned,
      chain.rel(p))
check("载入的是 .py", p.endswith(".py"), os.path.basename(p))
# 反例：不在当前程序清单里的编号，不能载入任何文件
app.on_pick("3")
check("节点 3 不在 ww 清单 -> 不载入文件", not app.editor.path
      or app.editor.path == p)
# ttk 的 cget("state") 在 Tk 8.6 可能返回 Tcl index 对象，统一转 str 比较
check("节点 3 -> 保存按钮禁用",
      str(app.btn_save.cget("state")) == "disabled",
      str(app.btn_save.cget("state")))

try:
    app.destroy()
except tk.TclError:
    pass

print("\n" + "=" * 74)
if FAIL:
    print(f"失败 {len(FAIL)} 项：")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("全部自检通过。")
