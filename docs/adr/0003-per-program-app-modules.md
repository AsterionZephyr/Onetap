# 3. 每个目标程序一个专项模块（orchestrator/apps/<key>.py）

日期：2026-10-19

## 状态

已接受，**三个阶段全部落地**：

- 阶段一/二（MaaEnd）：定位 + 判据 → 节点 8 执行与等待。
- 阶段三（ok-ww / ok-nte）：定位、判据、节点 8 全部搬迁。

三个程序现在各有一份 `orchestrator/apps/<key>.py`（ww 598 / nte 871 / zmd 1011 行），
共用文件里只剩程序无关的机制与垫片。

## 背景

三个目标程序（ok-ww / ok-nte / MaaEnd）共用同一条九节点链（2026-10-22 起改为**每程序一份清单**，
见 [ADR 0005](./0005-per-program-node-chain.md)；本 ADR 的「按程序切模块」不受影响），但差异是**结构性的**，
不是参数性的：

| | ok-ww | ok-nte | MaaEnd |
| --- | --- | --- | --- |
| 层数 | 两层（Tauri 壳 + Qt 第二层） | 两层 | **单层**（自己持窗口） |
| 窗口类 | `Qt*` 前缀 | `Qt*` 前缀 | `Tauri Window` 精确相等 |
| 界面 | 侧栏 + 全局任务列表 | 侧栏 + 多行复选列表 | **单页**，无侧栏、无行结构 |
| 定位范式 | 截图模板互相关 | 青色色块 + 行结构 | 绿色色块 + 底部带 |
| 完成信号 | 任务日志终止标记 | 任务日志终止标记 + 逐项汇总 | **Rust 后端日志** + 时间戳闸 |
| 跑完后 | 自行退出 | 自行退出 | 不立即退出 |

这些差异代码原先散落在三个**共用**文件里：`orchestrator/match.py`（三个程序的定位器）、
`orchestrator/verdict.py`（三个程序的终态判据）、`orchestrator/steps/step8_run_task.py`
（节点 8 的执行与等待）。于是：

- 改 MaaEnd 要在 `match.py` / `verdict.py` 里动手，改 ok-nte 也在同一个文件里动手 ——
  **反向同样成立**。文件尾部追加（`# 追加段`）这种应急手段已经出现过一次。
- 波及是**静默**的：定位器改坏只表现为「匹配分数仍高但位置错」「判据恒 unknown」，
  不抛异常、不返回错误码（INV-30 同一类失败）。
- 共用文件里三个程序的常量与范式混在一起，读代码的人无法从文件边界看出
  「这块属于谁、改它要回归谁」。ok-nte 首次接入时的教训就是这个：复制粘贴 ok-ww
  的节点代码会得到两份各自漂移的常量。

## 决策

1. **按程序切模块**：`orchestrator/apps/<programs.Program.key>.py`（`ww` / `nte` / `zmd`）
   承载该程序的**全部专属逻辑**：定位器、身份证据、终态判据、节点 8 的执行与等待。
2. **共用内核保持无程序知识**：`orchestrator/` 下其余模块（`capture` / `win32` / `input` /
   `window` / `state` / `steps/*` / `match` 的通用算法 / `verdict` 的通用 `LogWindow`）
   只提供机制，不认识具体程序。注册数据（exe、标题、窗口类、日志目录）仍在
   `programs.py` —— 它是 `targets` 与 GUI 的唯一来源，且必须能被轻量 import。
3. **入口唯一**：`apps.get(key)` 懒 import；未迁移的程序**抛 KeyError 不回落**
   （否则会出现「以为改了专项模块、其实改的还是共用文件」）。
4. **旧位置保留垫片**：`match.zmd_locate_start`、`verdict.ZmdLogWindow`、`step8.navigate_to_tasks`
   等仍是**同一个对象**，旧调用点与 `probe/*selfcheck` 零改动。
   共用层（`match` / `verdict`）用 **PEP 562 惰性垫片**（`_EXPORT_OWNER` 表 + 模块级
   `__getattr__`），因为模块级 `from .apps.x import ...` 会让 `apps/x.py → match → apps/x` 成环；
   `step8` 在文件末尾用普通 re-export（它没有人反向 import）。
   垫片位置都写死一句「新增逻辑请改 apps/<key>.py，不要加回本文件」。
5. **专属模块不得 import `steps/step8_run_task`**（step8 文件末尾 re-export 了 apps 的名字，
   反着 import 会成环）；对 `match` / `verdict` 只允许用**共用内核**（模板匹配、☰ 检测、
   侧栏项检测、`LogWindow`）；已迁走的名字一律经共用层的垫片惰性取用。
   共享的**叶子常量**放无依赖模块：`orchestrator/statuses.py`（终态字符串、节点结果字符串、
   以及 ok-script 两程序共用的终止标记 `TERMINAL_MARK_EXIT_GAME`）。
6. **改共用层必须三程序回归**：共用层不属于任何程序，所以它是唯一仍然「一改三动」的地方，
   这条规则把「波及」从意外变成流程（回归清单见下）。

## 考虑过的替代方案

**不分文件，继续用 `if prog.key == ...` 分派**（现状）。被否：分派能表达差异，但
不能约束**归属** —— 改一个程序的代码不需要动别的程序的文件，可是也没有任何东西
阻止它被写进共用文件。实测已经发生过一次（MaaEnd 的 700 余行追加在三个共用文件尾部）。

**每个程序一份完整链条拷贝**（`steps/ww/`、`steps/nte/` …）。被否：九节点骨架与
不变量校验是**真正共用**的（抓帧校验、前台判定、目标顶层判定、state.json 协议），
复制三份等于让不变量有三个实现，任何一个修 bug 都要改三处 —— 相反的静默风险。

**把程序差异全部数据化（配置驱动）**。被否：差异是结构性的。MaaEnd 没有侧栏和
任务行，ok-nte 的「开始」出现在三个页面需要页面锚点，ok-ww 只有单行 —— 这三件事
无法用同一组参数表达。能数据化的（exe、标题正则、窗口类、层数、日志目录、
进程名）**已经**全部在 `programs.py` 里，剩下的强行数据化只会得到一个 if 表。

## 后果

**正面**：
- 归属清晰：改 MaaEnd 只改 `orchestrator/apps/zmd.py`，影响面就是这个文件。
- 共用文件瘦身到位：`match.py` 1151 → **533 行**、`verdict.py` 960 → **325 行**、
  `steps/step8_run_task.py` 1244 → **363 行**，只剩程序无关机制 + 垫片。
- 程序之间的依赖被物理切断：`apps/ww.py` 只 import 共用内核与 `statuses`，
  不再在任何意义上「拥有」ok-nte 的代码。
- 专项模块可以有自己的自检脚本（`probe/zmd_locate_selfcheck.py` 等），
  改完就跑，不必拉起程序。

**负面，且必须承担**：
- 多一层间接：`apps.get(key)` + 垫片，读代码时确实要在两个文件间跳一次。
- 垫片是**过渡态**，会长期存在（旧调用点、GUI、probe 都在用）；它们必须保持
  「同一个对象」，不能变成副本。
- **MaaEnd 已迁完**（阶段一 + 阶段二）。`step8_run_task.py`（阶段二末 1244 → 964 行，阶段三末 363 行）现在只剩
  程序无关骨架：`shot` / `frame_changed` / `finish` 与 `CLICK_*` 阈值已抽到新的
  `orchestrator/frameops.py`。`CHANGE_THRESHOLD` 也**定义在 frameops**（不是 orchestrator.py），
  否则会出现 `apps/zmd → frameops → orchestrator → match → apps/zmd` 循环 import
  —— 实测报 `cannot import name 'ZMD_BOTTOM_FRAC' from partially initialized module`。
  同类问题的通法：常量下沉到叶子模块，由共用层反向取。
- **阶段三的教训：搬迁的真正风险是「模块全局名字」**。把函数搬走之后，留在共用层的
  代码里那些**裸名字**（`NTE_LOGDIR`、`NTE_TERMINAL_MARK`、`match.x`）不再能解析 ——
  PEP 562 的 `__getattr__` 只管 `module.attr` 这种属性访问，**不管函数体内的全局查找**
  （LOAD_GLOBAL 直接查模块 `__dict__`）。本次 `pyflakes` 一次性抓出 5 处：
  `verdict.py` 的 `NTE_LOGDIR`、`apps/nte.py` 的 3 处裸 `match.`、`apps/ww.py` 的
  `NTE_TERMINAL_MARK` 与 4 处裸 `match.`、`step8` 的 `grab`。
  两处是**真会炸**的（`LogWindow()` 默认目录、`ww_verdict` 的终止标记 —— 后者会让
  ok-ww 判据永远认不出终止标记 ⇒ 恒 RUNNING，属于静默失效）；其余在分支里，要跑到才炸。
  ⇒ 规矩：搬完之后**必须跑 `python -m pyflakes orchestrator`**，只看 undefined name 那一行。
- **一个常量现在有两个程序在认**：`TERMINAL_MARK_EXIT_GAME` 是 ok-ww 与 ok-nte 共用的
  终止标记字面量，迁走后各自持名（`WW_TERMINAL_MARK` / `NTE_TERMINAL_MARK`），
  但**字面量只在 `statuses.py` 写一遍** —— 各写一遍会漂移，漂移的后果同样是恒 RUNNING。
- 搬迁时**顺带抓出两个真 bug**（同一个「从来没走到的」弱证据分支，`apps/zmd.py`
  `zmd_click_and_confirm` 里）：`frame_changed()` 返回 `(changed, why)` 元组，旧代码判
  `if changed is True` ⇒ 恒假，分支永不生效；而它传的还是 `Frame` 对象（该函数只吃
  RGB ndarray）⇒ 真走到会 `AttributeError: 'Frame' object has no attribute 'astype'`。
  已修，新增 `probe/zmd_click_selfcheck.py`（4 用例）覆盖；记入 `HANDOFF.md` §2.1 第 15 条。
  教训：**搬迁时最值钱的收获就是「从没执行到的分支」**。
- 共用层**仍然一改三动**。这一点靠规则（第 6 条）与回归清单兜，不靠文件边界。

## 验收（本阶段实测）

迁移后全绿（`D:\WORKs\Anaconda\python.exe`，`$env:PYTHONIOENCODING="utf-8"`）：

| 自检 | 结果 |
| --- | --- |
| `probe/zmd_locate_selfcheck.py` | exit 0（真实帧定位 box=(744,772,856,812)） |
| `probe/zmd_verdict_selfcheck.py` | exit 0（真实日志切片回放） |
| `probe/zmd_wait_selfcheck.py` | exit 0（stub 窗口 + 日志回放，3 用例） |
| `probe/zmd_click_selfcheck.py` | exit 0（4 用例：日志确认 / pretask 失败 / 仅画面变化 / 无效果） |
| `probe/_probe_ww_verdict.py` | exit 0（ok-ww 判据回归，未受影响） |
| `probe/_probe_executor_pause.py` | exit 0（ok-nte FAULT #30 判据；两处源码断言已指向 `apps/nte.py` 与 `frameops.py`） |
| `probe/_probe_logwindow_arming.py` | exit 0（9/9，`LogWindow` 预武装） |
| `probe/_probe_frame_changed.py` | exit 0（11/11） |
| `probe/apps_shims_selfcheck.py` | exit 0（13/13 个 `is` 同一对象；`programs`/`targets` 自检空） |
| `step8 --target zmd --offline --adopt-frame` | exit 0（定位成功 (800,792)） |
| `python -m compileall -q orchestrator` | exit 0 |
| `python -m pyflakes orchestrator` | **0 个 undefined name** |
| `probe/zmd_preflight.py` | exit 0 |

且 `match.zmd_locate_start is apps.get("zmd").zmd_locate_start`、
`verdict.ZmdLogWindow is apps.get("zmd").ZmdLogWindow`（垫片是同一对象，不是副本）。

## 共用层回归清单（改 `capture` / `input` / `window` / `state` / `steps/*` 时必跑）

1. `probe/zmd_locate_selfcheck.py`、`probe/zmd_verdict_selfcheck.py`、
   `probe/zmd_wait_selfcheck.py`、`probe/zmd_click_selfcheck.py`
2. `probe/_probe_ww_verdict.py`（ok-ww 判据）、`probe/_probe_executor_pause.py`（ok-nte 判据）、
   `probe/_probe_logwindow_arming.py`（`LogWindow` 预武装）
3. `probe/apps_shims_selfcheck.py`（垫片必须仍是**同一对象**）
4. `python -m compileall -q orchestrator` + `python -m pyflakes orchestrator`（undefined name 为 0）
5. `step8 --target zmd --offline --adopt-frame logs/probe/zmd_full.png --only-locate`
6. `probe/activate_selfcheck.py`（改 `input`/`win32` 时必跑：置前台兜底点击的落点验证，FAULT #36）
7. 有程序的机器上：`--target <key> --dry-run`（ww/nte/zmd 各自一次）
8. `probe/_check_workspace.py`（**目录契约门禁**：根目录只放三份文件、`docs/` 只放文档、README 目录表对得上、无垃圾残留；exit≠0 即违约）

> **后续（2026-10-22）**：[ADR 0005](./0005-per-program-node-chain.md) 已把**节点链清单**拆到每个程序
> （`apps/<key>/nodes/__init__.py` 的 `NODES`）；本 ADR 的「按程序切模块」**仍然有效**，只是
> `apps/<key>.py` 现在是 `apps/<key>/` 包、节点实现放在 `apps/<key>/nodes/`，文中
> `steps/step8_run_task.py` 等路径是拆分前的形态。
