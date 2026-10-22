# 终态判定与清理

> **这份文档回答**：一次运行到底算「完成 / 失败 / 超时 / 未知」，以及跑完、超时、异常之后怎么收尾。
> **不回答**：不变量本身（见 [FRAMEWORK.md](./FRAMEWORK.md) §1）、怎么跑（见 [RUNBOOK.md](./RUNBOOK.md)）、
> 这些结论怎么测出来的（见 [HISTORY.md](./HISTORY.md)）。
>
> 一句话：**判定是框架自己的责任，不能指望程序的界面。**

## 1. 总原则

| 原则 | 说明 |
| --- | --- |
| 判定由框架做 | 程序的界面既不能区分「完成」与「失败回落」，也不能区分「还在跑」与「卡死」 |
| 证据不足报 UNKNOWN | INV-29/30：宁可报未知，也**绝不默认成功** |
| 每程序一个判据模块 | `orchestrator/apps/ww.py::ww_verdict`、`apps/nte.py::nte_verdict`、`apps/zmd.py::zmd_verdict`（+ `ZmdLogWindow`） |
| 分派显式 | `orchestrator/verdict.py::verdict_for(program=…)`；未知程序**抛错**，不回落默认（避免「以为在判 A 实际判了 B」） |
| 判据不同不能复用 | ok-ww 用阶段序列，ok-nte 用终止标记 + 逐项标记，MaaEnd 只用日志信号 —— 三者不可互换 |

## 2. 三程序判据总表

| 项 | ok-ww | ok-nte | MaaEnd（zmd） |
| --- | --- | --- | --- |
| 状态判定依据 | 读**进度面板**文字（横幅 `运行中`/`已完成`、`current task`、错误栏） | **页面锚点 + 动作元素**（行扫描是否仍找到「开始」） | **只读 `mxu-tauri.log`**（运行期**不抓帧**） |
| 阶段标记 | `info_set current task <phase>`（**丰富**） | **无实质阶段**（只有 `wait main`/`in main`/`None`） | **无业务阶段行**；只有 `[start_tasks]` 提交段、`maa_get_all_states` 轮询、`IconRecognition` 读图 |
| **终止标记** | `MainThread ok:quit app`（始终最后一行） | `TaskExecutor:Successfully Executed Task, Exiting Game and App!` | `stop_agent_impl called for instance: <id>`（唯一明确信号） |
| 逐任务结果 | **无** | ✅ `DailyRoutineTask:success/failed/skipped: [...]` | **无**（只有每条 task 的 `post_task returned task_id`） |
| 目标游戏 | `Client-Win64-Shipping.exe` | `HTGame.exe` | `Endfield.exe` |
| 正常完成后进程 | 自行退出 | 自行退出 | **不退出**（进程消失既非成功也非失败） |

## 3. ok-ww：任务日志的阶段序列

### 3.1 日志位置与实现

- 日志：`E:/TOOLS/ScriptsGames/ok-ww/data/apps/ok-ww/working/logs/ok-script.log`（按日期轮转成 `ok-script.YYYY-MM-DD.log`）
- 实现：`orchestrator/apps/ww.py::ww_verdict`（历史原型 `probe/ww_verdict.py`，同一套规则）

阶段行形如：

```
TaskExecutor <某Task>:info_set current task <阶段名>
```

### 3.2 阶段全集（跨 8 份日志统计）

| 阶段名 | 含义 | 性质 |
| --- | --- | --- |
| `wait main esc=True` | 等待回到主界面 | 过渡态，非阶段 |
| `in main esc=True` | 已在主界面 | 过渡态，非阶段 |
| `claim daily` | 领日常 | **进度阶段 1** |
| `claim mail` | 领邮件 | **进度阶段 2** |
| `check weekly garden` | 检查周本花园 | **收尾阶段**（切到 GardenTask） |
| `check discarded echo` | 检查废弃声骸 | **收尾阶段**（最完整运行的末步，切到 MergeEchoTask） |
| `garden_start_game` / `garden_confirm` / `garden_next_day` / `garden_get_skip` / `garden_new_stage` / `garden_shop_buy` / `garden_shop_close` / `garden_not_interested` | 花园子阶段 | GardenTask 内部 |

⚠️ **提取必须用通用前缀** `TaskExecutor \w*Task:info_set current task (.+)`。
只匹配 `DailyTask:` 会**漏掉 8 个 garden 阶段**（开发中实际发生过）。

其他有用标记：

| 标记 | 含义 |
| --- | --- |
| `info_set current daily progress N` / `info_set total daily points N` | 当前进度 / 总点数 |
| `MainThread ok:quit app` | **终止标记**（始终是最后一行） |
| `Killing process(es) ... Client-Win64-Shipping` | 任务**主动关游戏**（收尾动作） |
| `is disabled, raise Exception` + `TaskDisabledException, continue` | **被中断** |

### 3.3 判定规则

| 判定 | 条件 |
| --- | --- |
| `SUCCESS` | 到达 `check weekly garden` 或 `check discarded echo` |
| `SUCCESS_PART` | 到达 `claim mail` 但未到 `check *`（可能被 TaskDisabled 中断） |
| `PARTIAL` | 只到 `claim daily` |
| `FAILED` | 出现 `TaskDisabledException` 且未达 `claim daily` |
| `NO_TASK` | 程序退出但无任务痕迹 |
| `RUNNING` | 无终止标记且进程仍在 |
| `UNKNOWN` | 其他（**证据不足，不报成功**） |

### 3.4 三个被证伪的信号（别再试）

| 信号 | 证伪 |
| --- | --- |
| `exit_event.is_set` | 8 份日志里 6 份是 `is not set`，其中 3 份**同样跑完了完整序列** ⇒ 只反映关窗路径，与成败无关 |
| 进程消失 | **正常完成会退出，卡在等待条件时被用户关掉也会退出** ⇒ 必须结合日志才能定性 |
| 界面状态（按钮/横幅） | 「开始按钮重新出现」由**成功**与**失败回落**两者共同造成，形态无法区分 |

### 3.5 一个日志文件会累积多次运行

实测一个日志文件里有 **1~10 段**运行。判定必须**分段**、只取最后一段
（`verdict_from_log(..., latest_only=True)`，按 `ok:quit app` 切段），
否则上一次运行的成功会被算到本次头上 —— 这是开发中**实际踩到、差点交付**的假阳性。
分段的具体做法与它失效的场景见 §6。

### 3.6 两个读日志时的坑

- 日志里的 `window:1920x1080` / `real:1920x1080` 是**游戏窗口**（`refreshAdb` 的目标），
  **不是 ok-ww 自己的窗口**（ok-ww 实测 1823×1000、1458×800）。不要拿它核对我们的帧尺寸。
- 日志里 125 处 `MouseResetTask:move mouse back (x, y)` ⇒ **ok-ww 会自己移动鼠标**，
  它和我们抢光标；这同时解释了 `GetCursorPos 拒绝访问` 报错的真实来源（不是提权，是它的归位任务在提权环境下读光标被拒）。

## 4. ok-nte：终止标记 + 逐项结果

### 4.1 状态判定

| 状态 | 判定方法 |
| --- | --- |
| **空闲** | 页面锚点命中 **且** 行扫描仍找到「开始」按钮 |
| **运行中** | 动作元素消失/变化（实测动作元素 score **1.0000 → 0.2968**） |

v1.4.8 起动作元素由**行扫描**得出（每行一个按钮），不再是「固定按钮模板的匹配分数」
（`2_nte.png` 已弃用）。

### 4.2 逐项标记（实测）

```
DailyRoutineTask:任务完成: <任务名>
DailyRoutineTask:任务失败: <任务名>
DailyRoutineTask:success: [...] failed: [...] skipped: [...]
DailyRoutineTask:结束执行日常任务
```

判定（简化后只看是否完成）：

```
SUCCESS : 出现终止标记，或出现「结束执行日常任务」
RUNNING : 无终止标记且进程在运行
NO_TASK : 无任何任务痕迹
UNKNOWN : 其他（证据不足不报成功）
```

**单项失败不改变判定**（用户决策：ok-nte 的单项目失败与本项目无关，逻辑只关注是否完成），
只在完成后打印：

```
逐项成功 6 项: ['异象界域','一咖舍','影院约会','喷泉签到','异象家具','羁遇赠礼']
跳过 1 项: ['异象追猎']
⚠ 失败 1 项（不影响流程判定）: ['日常领取']
```

⇒ ok-nte 的结果粒度比 ok-ww 好：能报出哪几项成功、失败、跳过。

### 4.3 ⚠️ 空闲态 ≠ 完成（**实测踩过的坑**）

「开始按钮重新出现」有两种原因，按钮形态**无法**区分：

| 原因 | 含义 |
| --- | --- |
| 任务全部成功完成 | ✅ 真正完成 |
| 任务失败/中断 | ❌ 回落 |

**实测教训**：ok-nte 回到空闲态，开发时据此判为「完成」，**实际是任务失败**
（用户指出：ok-nte 正常完成后**同样会自动退出**，那次未退出正因失败）。

⇒ 两程序正常完成都会自行退出，但**终态判定必须另有成功判据**：

| 手段 | 说明 |
| --- | --- |
| 完成提示 | ok-ww 有「每日任务已完成」+「成功执行任务, 正在退出游戏和App!」 |
| 交叉印证 | 退出**且**有完成提示 → 成功；退出**但无**提示 → 异常 |
| 程序日志 | ok-nte：`E:/TOOLS/ScriptsGames/ok-nte/logs/`（目录） |

### 4.4 STALLED（执行器暂停）—— 2026-10-18 真机闭环

ok-nte 的游戏窗口被最小化时，执行器先写哨兵
`update_window_size hwnd_window:og.executor.pause pos_invalid: (-32000, -32000, 0, 0)`，
然后**永久停住**（不抛异常、不写终止标记、不退出）。

判据链：节点 8 先给 `--stall-grace`（默认 **90s**）自行恢复；期间**零业务行 + 零收尾动作**
⇒ 判 `failed` 且 `data.result='stalled'`、`state.result='stalled'`，主控退出码 **3**。

实测（`probe/_probe_stalled_live.py --stall-grace 90`，run-dir `logs/runs/stalled-live-20261018-061325`）：

```
[阶段1] 已出现业务行 2 条 → ShowWindow(SW_MINIMIZE) = True
[哨兵]  06:14:32,699 ERROR ... og.executor.pause pos_invalid: (-32000, -32000, 0, 0)
节点 8  用时 135.8s，status=failed，data.result='stalled'
state   result='stalled'，主控退出码 3
```

- **STALLED 映射为 `failed`，不是 `timeout`**：「停住了」是**确定**的失败，不该再空等到运行超时上限。
- **判定以 `state.json` 的 `result` 为准**，而主控把结论写成**小写** `stalled` ——
  只 grep 大写 `STALLED` 会把已成功触发哨兵的轮次误报成「未触发」（本次踩过，探针已改）。

## 5. MaaEnd：完成 ≠ 进程退出，判据只看日志

### 5.1 事实

MaaEnd 跑完后 `MaaEnd.exe` **不会立刻退出**（与 ww/nte 相反）。
实测 22:26:37 完成 → 22:55:59 仍在 → 22:56:14 才出现 `[telemetry] 已结束 Session`，
**退出原因日志未记录**（没有 exit 命令行），无法判定是人工关闭还是自身退出。
⇒ 「进程消失」在它身上既非成功标志也非失败标志 —— 唯一的明确完成信号在日志里：

```
[2026-10-18][22:26:37][INFO][mxu_lib::commands::maa_agent] stop_agent_impl called for instance: yj2gs5w
```

### 5.2 信号表

| 信号 | 位置 | 用途 |
| --- | --- | --- |
| `stop_agent_impl called for instance: <id>` | `zmd/debug/mxu-tauri.log` | **主判据**（唯一明确终止信号） |
| `[start_tasks] All tasks submitted, total: N task_ids` | 同上 | 点击生效的确认（节点 8d） |
| `[MXU_KILLPROC] Killing process: <game>` | 同上 | 辅助完成证据（「关游戏」内置任务，实测排最后一条），**须注明** |
| `run_pretask finished with exit code: 1` | 同上 | **启动失败**（多半是启动器路径没配好） |

### 5.3 只认 `mxu-tauri.log`

同目录的 `<date>-<n>.log`（应用日志）与 `maafw.log`（框架日志）**每次启动都被清空重建**
（应用日志自己写着 `Auto-cleared log files and debug artifacts on launch`），不能作为跨运行判据。

### 5.4 两道闸：字节偏移 + 时间戳基线

`ZmdLogWindow.mark()` 记基线字节偏移**和**文件最后一行的时间戳，`poll()` 逐行丢弃 `< 基线` 的行。

**只按字节偏移是不够的**：日志变小/被清后整段重读，会把**上一次运行**的 `stop_agent_impl`
当成本次完成 ⇒ 假成功（INV-30 级别）。自检里做了反证：去掉时间戳闸，同一段文本确实判 SUCCESS。

### 5.5 读不到 ≠ 成功

文本为空时一律 `unknown`（**刻意**区别于 ok-nte 的 `running` —— `mxu-tauri.log` 跨启动追加，
「无新增」更像路径/权限/mark 时机坏了，而不是「还没开始」）。

### 5.6 辅助证据与 1 秒之差

`[MXU_KILLPROC] Killing process: <game>` 是 MaaEnd 自带的「关游戏」内置任务，实测排在提交队列**最后一条**，
可用作完成证据但**必须注明**；随后 1 秒内通常出现 `stop_agent_impl`
（实测 22:26:36 taskkill succeeded → 22:26:37 stop_agent_impl）。
故代码在关游戏后**继续在收尾宽限里 poll**：拿到主判据就用主判据，拿不到才退回辅助证据，
并**如实写明**「宽限期内未看到 stop_agent 标记」—— 否则事后读 `state.json` 的人会以为该信号从未出现。

### 5.7 运行期不抓帧

点完「开始任务」后 MaaEnd 拉起启动器与**全屏**游戏，MaaEnd 被盖住 ⇒ 抓帧拿到的是**游戏的像素**，
而且尺寸=rect、非全黑、颜色数够，**所有不变量都会通过** ⇒ 典型的静默分析错画面。
⇒ 等待阶段只读日志；抓帧只在**点击之前**（定位）与**失败排查**时做。

## 6. 「本次运行」的日志窗口（INV-36/37）

**⚠️ `ok:quit app` 不能作为「运行边界」** —— 被**外部强制终止**的运行不会写该标记，
相邻两次运行会被**合并成一段**，新运行会「继承」旧运行的成功汇总。

**实测假阳性**：编排在**点击后 1 秒**就报 `SUCCESS`，且「失败项」打印为空。
证据：`ok-script.log` 从 `01:24:26` 到 `02:56` 被当成**一整段**（段数=1）。
根因：`LogWatcher` 构造时 `read()` 读入**全部历史日志**，再按 `ok:quit app` 分段取最后一段；
而上一次运行是被**编排的兜底清理强杀**的，**没有写** `ok:quit app`。

⇒ **对策（INV-37）**：**先建立「本次运行」的文本窗口，再做匹配** ——
`LogWatcher` 只记录**基线字节偏移**，`accumulated()` 只返回新增内容。修复后：

```
[日志判据] UNKNOWN  | 日志为空        ← 启动时为空，不再借用历史
[日志判据] RUNNING  | 逐项: 完成 0 项
==> ok-nte: TIMEOUT  (超过 420s；日志判据=RUNNING)
```

⇒ 任何「读入全部历史再取最后一段」的判据都不可靠：分段的正确性依赖于上一次运行**正常收尾**。

**超时默认值定为 1200s**：实测一轮完整日常需 **7 分钟以上**（02:05→02:12），**420s 明显不够**。
MaaEnd 的整轮上限按实测另配（见 RUNBOOK 的参数表），运行超时见 `--run-timeout` / `--total-timeout`。

## 7. 实测结果

### 7.1 8 份历史日志的分类

| 日志 | 整文件判定 | 最后一段判定 | 段数 |
| --- | --- | --- | --- |
| 09-27 | SUCCESS | UNKNOWN | 2 |
| 09-28 | SUCCESS | SUCCESS | 1 |
| 09-29 | SUCCESS | UNKNOWN | 7 |
| 09-30 | NO_TASK | UNKNOWN | 3 |
| 10-01 | NO_TASK | UNKNOWN | 3 |
| 10-02 | SUCCESS | SUCCESS | 10 |
| 10-03 | SUCCESS | SUCCESS | 2 |
| `ok-script.log` | SUCCESS | 见 §6 | 3 |

「整文件」与「最后一段」判得不一样，正是因为一个文件累积多次运行（§3.5）。

### 7.2 端到端（修正后的一次完整运行）

| 时间 | 日志事件 |
| --- | --- |
| 01:07:12 | `claim daily` |
| 01:07:29 | `claim mail` |
| 01:07:55 | `check weekly garden`（切到 GardenTask） |
| 01:08:12 | `check discarded echo`（切到 MergeEchoTask） |
| 01:08:25 | `Killing process(es) ... Client-Win64-Shipping.exe` |

```
[7] 等待完成（最多 600s）
[日志判据] RUNNING  | 阶段达到: ['claim daily']          ← 先 RUNNING，证明读的是本次
[日志判据] SUCCESS  | 阶段达到: [四阶段齐全]
==> ok-ww: SUCCESS   用时 195s
```

新发现：除 `DailyTask` 还有 `GardenTask`、`MergeEchoTask`，阶段切换伴随**任务类切换**（§3.2 的通用前缀即因此而定）。

## 8. 清理策略

> 结论一句话：**目标程序平时会自己收尾，但超时/卡死时必须由框架按进程血缘强制清理**。
>
> ⚠️ 本节讲的是**进程**清理（该杀谁）。**日志文件**的保留是另一件事：`logs/runs/` 只保留最近十轮，
> 由 `orchestrator/logretention.py` 执行（GUI 每跑完一轮静默清理一次），策略与手工用法见 `docs/RUNBOOK.md` §11。

### 8.1 结论表

| 问题 | 答案 |
| --- | --- |
| 正常完成后目标会自行清理吗？ | ✅ **会，实测有效**（一次完整任务后进程表零残留） |
| 能依赖它吗？ | ❌ **不能** —— 超时/卡死时它不会退出，必须外部兜底 |
| 外部能清理吗？ | ✅ **能**。提权会话对任意进程具备 `PROCESS_TERMINATE` |
| 怎么识别该杀谁？ | **按进程血缘**（Toolhelp32），**不能**按「有无可见窗口」 |

### 8.2 目标会自行清理（实测）

一次完整 ok-ww 任务跑完后，进程表：

```
ok-ww 0 个   ok-nte 0 个   pythonw 0 个   Client-Win64-Shipping 0 个
```

日志末尾的收尾序列：

```
handler:handler stopping ...
TaskExecutor:Executor destroy
PyAppifyShutdown ok:Attempting to terminate process with PID: N
MainThread ok:quit app
```

### 8.3 `[WinError 5] 拒绝访问` **是良性的**

ok-ww 日志反复出现：

```
ERROR PyAppifyShutdown ok:Failed to terminate process with PID 6628: [WinError 5] 拒绝访问。
```

| 证据 | 说明 |
| --- | --- |
| `Kill Launcher After Start` | 每个日志都有 —— ok-ww **设计为「启动后杀掉第一层启动器」** |
| 被终止的 PID == 「被最小化的进程」PID | 目标就是**第一层启动器** |
| **首次 `Attempting` 总是成功** | 64 次 Attempting / 仅 22 次 Failed |
| 失败只出现在**对同一 PID 的重复尝试** | 该进程**已经退出** |

⇒ 成因是**进程已退出**（对已失效 PID 的 `OpenProcess` 返回 `ACCESS_DENIED`），**不是权限问题**。
⇒ 编排层**不应把它当作故障**。

### 8.4 提权会话的终止能力（实测）

| 目标 | `OpenProcess(PROCESS_TERMINATE)` |
| --- | --- |
| self (python) | ✅ OK |
| explorer | ✅ OK |
| DSH Desktop | ✅ OK |
| GameViewerServer | ✅ OK |

⇒ 提权框架可终止任意进程 ⇒ 兜底清理可行。

### 8.5 按血缘识别，不按窗口

- **实测踩坑**：最初用「该 pythonw 是否有可见窗口」识别第二层，结果**误跳过**了 ok-nte 的窗口持有者
  （`pythonw` pid 60660）—— 因为它当时**窗口还没创建**。
- **修正**：`CreateToolhelp32Snapshot` 取进程树，第二层 = **目标 exe 的后代**。
- **`wmic` 在本机不可用**：`wmic process get ProcessId,ParentProcessId` 返回 **0 条关系**
  （Win11 26200 已移除 wmic），改用 Toolhelp32 后拿到 334 条。
  ⚠️ 血缘判断若静默失效，会让清理「看起来跑了但什么都没杀」。
- **等待消失要用 `tasklist` 复核**：`OpenProcess` 探测在「已终止但句柄未释放」的窗口内仍可能成功，
  会误判为「仍未消失」。等待循环改用 `tasklist` 的全量 PID 集合判断。

实现：`orchestrator/cleanup.py`（历史原型 `probe/cleanup.py`）。

### 8.6 三条路径与白名单

```
正常路径：等目标自行清理 → 复核 → 无残留即通过
兜底路径：复核发现残留 → 按血缘强制清理
前置路径：编排开始前 --pre-clean，确保独占式前提
```

白名单（避免误杀）：

- 第一层：`<target>.exe`
- 第二层：**目标的血缘后代** `pythonw`
- 游戏进程：**默认不动**（`--keep-game` / `kill_game=False`）

节点 9 用**可执行路径前缀**区分同名的 `pythonw`：路径不在目标目录下的一律跳过
（本机同时跑着 ok-ww 与 ok-nte 的 `pythonw`，按进程名扫会误杀）。

### 8.7 局限

| 项 | 说明 |
| --- | --- |
| 血缘在目标已退出后失效 | 若第一层先于第二层退出，父子关系可能已断（Windows 保留 PPID 但进程可能已消失）；实现里加了「残留且有窗口」回退 |
| 游戏进程遗留 | 默认不动；任务中途超时则游戏可能仍在运行，需用户决策 |
| 未用更强手段 | 未用 `taskkill /T /F` 整树强杀；逐 PID 终止已够用 |
| MaaEnd 的伴生进程 | `agent/go-service.exe`、`cpp-algo.exe` 属其正常血缘；`msedgewebview2` **不可**纳入归属判断 |

## 9. 待验证

| 项 | 说明 |
| --- | --- |
| `check discarded echo` 是否总是最后一步 | 6 份成功日志均是，样本有限 |
| 等待态（`请在大世界并在队伍中开始！`）在日志中的样貌 | 需一次真实的等待态运行 |
| `TaskDisabledException` 的确切触发条件 | 本次是「走到 `claim mail` 后被中断」，原因未明 |
| MaaEnd 退出原因 | 日志未记录 exit 命令行，无法区分人工关闭与自身退出 |
