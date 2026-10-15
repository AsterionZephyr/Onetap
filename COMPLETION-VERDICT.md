# Q1：ok-ww 完成判据（基于日志）

> **问题**：编排层需要可靠的"任务是否成功完成"判据。
> 仅靠"进程消失"不可靠 —— **进程消失 ≠ 成功**（INV-29/30）。
> 实测日期：本次会话。依据 8 份历史日志 + 代码实测。

---

## 1. 结论先行

**可靠判据在 ok-ww 自己的任务日志里**，而非界面或进程状态。

**日志位置**：`E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs\ok-script.log`
（按日期轮转：`ok-script.YYYY-MM-DD.log`）

**实现**：`probe/ww_verdict.py`

---

## 2. 判据：任务阶段序列

日志中的阶段标记：

```
TaskExecutor DailyTask:info_set current task <阶段名>
```

**实测阶段全集**（跨 8 份日志统计，**放宽前缀后为 14 个值**）：

| 阶段名 | 含义 | 性质 |
| --- | --- | --- |
| `wait main esc=True` | 等待回到主界面 | 非阶段（过渡态） |
| `in main esc=True` | 已在主界面 | 非阶段（过渡态） |
| `claim daily` | 领日常 | **进度阶段 1** |
| `claim mail` | 领邮件 | **进度阶段 2** |
| `check weekly garden` | 检查周本花园 | **收尾阶段** |
| `check discarded echo` | 检查废弃声骸 | **收尾阶段（最完整运行的末步）** |
| `garden_start_game` | 花园：启动游戏 | GardenTask 子阶段 |
| `garden_confirm` | 花园：确认 | 同上 |
| `garden_next_day` | 花园：下一天 | 同上 |
| `garden_get_skip` | 花园：跳过 | 同上 |
| `garden_new_stage` | 花园：新阶段 | 同上 |
| `garden_shop_buy` | 花园：商店购买 | 同上 |
| `garden_shop_close` | 花园：关闭商店 | 同上 |
| `garden_not_interested` | 花园：不感兴趣 | 同上 |

⚠️ **阶段来自不同的任务类**（实测 `DailyTask` / `GardenTask` / `MergeEchoTask`）。
故提取必须用**通用前缀**：`TaskExecutor \w*Task:info_set current task (.+)`，
**只匹配 `DailyTask:` 会漏掉 8 个 garden 阶段**（开发中实际发生过）。

其他有用标记：

| 标记 | 含义 |
| --- | --- |
| `info_set current daily progress N` | 当前进度 |
| `info_set total daily points N` | 总点数 |
| `MainThread ok:quit app` | **终止标记**（始终是最后一行） |
| `Killing process(es) ... Client-Win64-Shipping` | 任务**主动关闭游戏**（收尾动作） |
| `is disabled, raise Exception` + `TaskDisabledException, continue` | **被中断** |

---

## 3. 不可用的信号（**实测证伪**）

### 3.1 `exit_event.is_set` —— 我最初的假设，**是错的**

| 日志 | exit_event | 任务是否跑完 |
| --- | --- | --- |
| 09-27 | `is_set` | ✅ 完整 |
| 09-28 | `is_set` | ✅ 完整 |
| 09-29 | **`is not set`** | ✅ **完整** |
| 10-02 | **`is not set`** | ✅ **完整** |
| 10-03 | **`is not set`** | ✅ **完整** |

⇒ **6/8 是 `is not set`，其中 3 份同样跑完了完整任务序列。**
⇒ 它只反映"关窗路径"，**与任务成败无关**。

### 3.2 进程消失 —— 不足

ok-ww 在**正常完成**后会自行退出，但：
- **卡在等待条件**时也会被用户关闭（退出但未完成）；
- 故"退出"必须**结合日志**才能定性。

### 3.3 界面状态（按钮/横幅）—— 不足

"`▶ 开始` 重新出现"可由**成功完成**或**失败回落**两者造成，无法区分。

---

## 4. 判定规则（`ww_verdict.py`）

| 判定 | 条件 |
| --- | --- |
| `SUCCESS` | 到达 `check weekly garden` 或 `check discarded echo` |
| `SUCCESS_PART` | 到达 `claim mail` 但未到 `check *`（可能被 TaskDisabled 中断） |
| `PARTIAL` | 只到 `claim daily` |
| `FAILED` | 出现 `TaskDisabledException` 且未达 `claim daily` |
| `NO_TASK` | 程序退出但无任务痕迹 |
| `RUNNING` | 无终止标记且进程仍在 |
| `UNKNOWN` | 其他（**证据不足，不报成功**） |

---

## 5. 分类结果（8 份历史日志）

| 日志 | 整文件判定 | **最后一段**判定 | 段数 |
| --- | --- | --- | --- |
| 09-27 | SUCCESS | UNKNOWN | 2 |
| 09-28 | SUCCESS | SUCCESS | 1 |
| 09-29 | SUCCESS | UNKNOWN | 7 |
| 09-30 | NO_TASK | UNKNOWN | 3 |
| 10-01 | NO_TASK | UNKNOWN | 3 |
| 10-02 | SUCCESS | SUCCESS | 10 |
| 10-03 | SUCCESS | SUCCESS | 2 |
| ok-script.log | SUCCESS | 见下 | 3 |

⚠️ **一个日志文件会累积多次运行**（实测 1~10 段）。故判定必须**分段**，否则上一次运行的成功会被算到本次头上 —— 这正是我在开发中**实际踩到并差点交付的假阳性**。

---

## 6. 两次自纠（本次 Q1 工作中）

### 6.1 「`exit_event.is_set` 可判成功」—— **错的**

见 §3.1。实测 6/8 是 `is not set` 而任务照样跑完。

### 6.2 「日志判据报 SUCCESS」—— **第一次是假阳性**

第一次接入日志判据后，编排在点击后 **1 秒**就报 `SUCCESS`。
原因：`LogWatcher` 启动时读入**全部既有日志**，而 `ok-script.log` 里**含上一次运行的完整序列**。

**修正**：`verdict_from_log(..., latest_only=True)` 按 `ok:quit app` **切分运行段**，只取最后一段。
修正后，同一次运行先报 `RUNNING`（只有 `claim daily`），再逐步推进到完整序列 —— **这才是真实证据**。

---

## 7. 端到端验证（已通过）

修正后的完整运行（独立复核）：

| 时间 | 日志事件 |
| --- | --- |
| 01:07:12 | `claim daily` |
| 01:07:29 | `claim mail` |
| 01:07:55 | `check weekly garden`（切换到 **GardenTask**） |
| 01:08:12 | `check discarded echo`（切换到 **MergeEchoTask**） |
| 01:08:25 | **`Killing process(es) ... Client-Win64-Shipping.exe`** |

编排日志：

```
[7] 等待完成（最多 600s）
[日志判据] RUNNING  | 阶段达到: ['claim daily']          ← 先 RUNNING，证明读的是本次
[日志判据] SUCCESS  | 阶段达到: [四阶段齐全]
==> ok-ww: SUCCESS   用时 195s
```

**退出码 0。**

**新发现**：除 `DailyTask` 外，还有 **`GardenTask`** 与 **`MergeEchoTask`** —— 阶段切换伴随**任务类切换**：
```
TaskExecutor GardenTask:info_set current task ...
TaskExecutor MergeEchoTask:info_set current task ...
```
故阶段提取不能只匹配 `DailyTask:`，应用**通用前缀** `TaskExecutor \w+Task:info_set current task (.+)`。
（当前实现用的是 `DailyTask:info_set current task`，恰好覆盖了这四个阶段，但**应放宽**。）

---

## 8. 重要副产品：三个此前未知的事实

### 6.1 **ok-ww 会自己移动鼠标**

日志中 125 处 `MouseResetTask:move mouse back (x, y)`。

⇒ **它会与我们抢光标。** 编排层在点击后若依赖光标位置，可能被它重置。
⇒ 这也解释了 `MouseResetTask:mouse_reset exception ... GetCursorPos 拒绝访问` —— **事实记录 §2.5 那条"良性报错"的真实来源找到了**：不是"无边框窗口插件"，而是 **ok-ww 自己的鼠标归位任务**在提权环境下读光标被拒。

### 6.2 ok-ww 关不掉自己的子进程

每份日志都有：

```
ERROR PyAppifyShutdown ok:Failed to terminate process with PID NNNNN: [WinError 5] 拒绝访问。
```

⇒ **ok-ww 自己也会遇到"拒绝访问"**（与事实记录 §2.2 同源）。
⇒ 对编排层：**清理阶段不能假定 ok-ww 已把自己收拾干净**，可能需外部强制清理。

### 6.3 日志里的窗口尺寸 ≠ 我们测的

日志：`window:1920x1080`、`real:1920x1080`（**游戏窗口**）
我们测：ok-ww 窗口 `1823x1000` 等

⇒ 日志中的 `hwnd_window` 指的是**游戏**窗口（`refreshAdb` 的目标），**不是 ok-ww 自己的窗口**。注意区分。

---

## 7. 对编排层的接入

`orchestrator.py` 已改为：

1. 运行前记录日志**基线偏移**（只看本次新增）；
2. 等待循环中每 5s 读取新增日志并调 `verdict_from_log`；
3. **以日志判据裁决终态**，界面状态仅作记录；
4. 进程消失时**仍以日志作最终裁决**，而非直接判 UNKNOWN。

**修正效果**：此前 15:58 那次运行被编排判为 `TIMEOUT`，而日志判据为 `SUCCESS_PART` —— **编排当时过于悲观**。

---

## 8. 待验证

| 项 | 说明 |
| --- | --- |
| `check discarded echo` 是否总是最后一步 | 6 份成功日志均是，但样本有限 |
| 等待态（`请在大世界并在队伍中开始！`）在日志中的样貌 | 需一次真实的等待态运行来确认 |
| `TaskDisabledException` 的确切触发条件 | 本次是"走到 claim mail 后被中断"，原因未明 |
