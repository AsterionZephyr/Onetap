"""docs/_probe_gui2_stepnote.py — 节点 8 的长 note 会不会把左栏撑宽（A/B 实测）

背景（用户 2026-10-20 截图）：节点 8 完成后，一句话的完成汇报把「步骤状态」
左栏顶宽到 ~380px，右侧日志被挤窄。修法见 `gui/app.py` 的
`NOTE_MAX` / `NOTE_WRAP` / `_short_note()`。

本脚本**真开窗口**（不是拼字符串算宽度），把
`logs/runs/run-20261020-191419/nte/state.json` 里节点 8 的**真实 note**
注入界面，然后量三种状态下「左栏 / 右侧日志」的实际像素宽度：

    基线     节点 8 没有 note（= 未跑 / 刚起）
    旧行为   sub 标签 wraplength=0（无限制）+ note 全文   <- 用户看到的那版
    新行为   sub 标签 wraplength=NOTE_WRAP + _short_note()

判据：新行为左栏宽度 ≈ 基线（不再被 note 撑开），且**明显小于**旧行为。

跑法：
    & "D:\\WORKs\\Anaconda\\python.exe" -X utf8 docs\\_probe_gui2_stepnote.py [秒数]

不带参数默认保持窗口 20 秒供截屏（项目原则：抓图必须落盘供肉眼复核）。
"""

import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.app import App, NOTE_MAX, NOTE_WRAP, _short_note  # noqa: E402

HOLD = int(sys.argv[1]) if len(sys.argv) > 1 else 20

# run-20261020-191419/nte/state.json 节点 8 的原文，一个字都没改
RAW_NOTE = (
    "completed：汇总 success=['异象界域', '一咖舍', '日常领取', '影院约会', "
    "'喷泉签到', '异象家具', '羁遇赠礼'] failed=[] skipped=['异象追猎']；"
    "终止标记=True 日常结束=True 杀游戏=False；出现终止标记（进程收尾）")

# 同一轮里其它节点的 note（都短，用来当"正常页"的参照）
OTHER = {
    "1": ("ok", "已提权"),
    "2": ("ok", "已启动 E:\\TOOLS\\ScriptsGames\\ok-nte\\ok-nte.exe"),
    "4": ("ok", "第二层 Qt 窗口就绪 hwnd=461292"),
    "5": ("ok", "就绪 1500x1000"),
    "6": ("ok", "1500x1000 身份 1.0000"),
    "7": ("ok", "已置前台且校验通过"),
    "9": ("ok", "正常完成，未杀任何进程（游戏侧仍有 1 个进程存活）"),
}

app = App(dry_run=True)
app.geometry("1280x780+40+40")
app.update()

left = app.lbl_scope.master          # 左栏 Labelframe「目标与步骤」
row8 = app.node_rows["8"]


def widths(tag):
    app.update_idletasks()
    app.update()
    print(f"  {tag:<22} 左栏={left.winfo_width():>4}px  "
          f"步骤列表={app.run_list.winfo_width():>4}px  "
          f"日志={app.log_text.winfo_width():>4}px", flush=True)
    return left.winfo_width(), app.log_text.winfo_width()


for sid, (st, note) in OTHER.items():
    app.set_node("nte", sid, st, note)

print(f"note 原文 {len(RAW_NOTE)} 字符；NOTE_MAX={NOTE_MAX} "
      f"NOTE_WRAP={NOTE_WRAP}", flush=True)
print(f"  摘要 = {_short_note(RAW_NOTE)!r}", flush=True)
print(f"  未截断时该行文本的**请求宽度** = "
      f"{tk.Label(app, text=RAW_NOTE, font=('Microsoft YaHei UI', 8))"
      f".winfo_reqwidth()}px", flush=True)
print("实测宽度（A/B，同一窗口、同一 note）:", flush=True)

# --- 基线：节点 8 还没有 note -----------------------------------------------
app.set_node("nte", "8", "ok", "")
w_base, log_base = widths("基线（无 note）")

# --- 新行为：走 _paint 的正常路径 -------------------------------------------
app.set_node("nte", "8", "ok", RAW_NOTE)
w_new, log_new = widths("新：摘要+wraplength")

# --- 旧行为：把 wraplength 关掉、塞回全文（= 用户截图那一版） ----------------
row8["sub"].config(wraplength=0, text=RAW_NOTE)
w_old, log_old = widths("旧：全文+wraplength=0")

# --- 恢复界面，留给截屏看 ---------------------------------------------------
row8["sub"].config(wraplength=NOTE_WRAP)
app.set_node("nte", "8", "ok", RAW_NOTE)
w_final, _ = widths("恢复（给截屏看）")
app.set_current("9", "退出与清理", "ok", target="nte")
app.append_log("[结果] " + RAW_NOTE)
app.append_log("[节点 8] -> OK   " + _short_note(RAW_NOTE))

print("", flush=True)
print(f"旧 - 新 = {w_old - w_new}px（期望 > 0：摘要确实省下了宽度）", flush=True)
print(f"新 - 基线 = {w_new - w_base}px（期望 ≈ 0：长 note 不再撑宽左栏）", flush=True)
ok = (w_old - w_new) > 20 and abs(w_new - w_base) <= 20
print(("PASS" if ok else "FAIL") + "：右栏日志宽度 "
      f"旧={log_old}px 新={log_new}px 基线={log_base}px", flush=True)
assert app.node_rows["8"]["sub"].cget("wraplength") == str(NOTE_WRAP), "wraplength 没恢复"

app.after(HOLD * 1000, app.destroy)
print(f"窗口保持 {HOLD} 秒供截屏（节点 8 应显示一行摘要，左栏不宽）。", flush=True)
app.mainloop()
print("DONE", flush=True)
