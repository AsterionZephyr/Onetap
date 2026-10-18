# 断点式编排（`orchestrator/steps/`）

> **这份文档回答**：怎么按节点单独跑、出错时改哪一份、怎么接着往下跑。
> 上游依据：[README-ORCHESTRATOR.md](./README-ORCHESTRATOR.md) §5「编排流程」、
> [IMPLEMENTATION-0.1.md](./docs/IMPLEMENTATION-0.1.md)、[FRAMEWORK.md](./FRAMEWORK.md)。

---

## 1. 为什么拆

原来 `orchestrator/orchestrator.py` 的 `run()` 是**一条一气呵成的链条**：
它顺序调用 `node1..node9`，中途任何一环出错，都要：

- 打开那个 **479 行**的文件找位置；
- 改完之后**从头重跑整条链**（启动 + 等窗口 + 抓帧，实测 1~2 分钟起）；
- 期间**其他环节的状态全部丢失**。

拆成**每节点一个脚本**后，任意一环出错都能：

1. **只打开那一份**代码（每个文件 1.5~18 KB，职责单一）；
2. **只重跑那一份**（秒级，不重新启动程序）；
3. 其他环节的**代码与状态原样不动**。

---

## 2. 节点与文件对照

| 节点 | 名称 | 文件 | 对应 README §5 |
| --- | --- | --- | --- |
| 1 | 提权检查 | [step1_check_admin.py](./orchestrator/steps/step1_check_admin.py) | 前置 |
| 2 | 启动目标程序 | [step2_launch.py](./orchestrator/steps/step2_launch.py) | `[1]` 前半 |
| 4 | 等待窗口持有者 | [step4_wait_second_layer.py](./orchestrator/steps/step4_wait_second_layer.py) | `[1]` 后半 |
| 5 | 等待窗口就绪 | [step5_wait_ready.py](./orchestrator/steps/step5_wait_ready.py) | `[2a]` 前置 |
| 6 | 抓首帧 + 校验 + 身份 | [step6_first_frame.py](./orchestrator/steps/step6_first_frame.py) | `[2a]` 抓帧 |
| 7 | 置前台 + 可用性校验 | [step7_foreground.py](./orchestrator/steps/step7_foreground.py) | `[2]` |
| 8 | 任务循环 | [step8_run_task.py](./orchestrator/steps/step8_run_task.py) | `[4]` `[5]` `[6]` `[7]` |
| 9 | 退出与清理 | [step9_cleanup.py](./orchestrator/steps/step9_cleanup.py) | `[7]` 兜底 |
| — | **主控** | [main.py](./orchestrator/steps/main.py) | 按顺序启动 |
| — | 交接面 | [context.py](./orchestrator/steps/context.py) | state.json 契约 |

**没有节点 3**：实机复核证明「跨过第一层」这道关卡不存在
（见 [window.py](./orchestrator/window.py) 模块说明）。

---

## 3. 怎么跑

### 3.1 一键跑完（最简单）

```powershell
cd E:\TOOLS\ScriptsGames\Onetap

# 先空跑（只校验与定位，不点击）
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.main --dry-run

# 完整执行
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.main
```

主控**不含任何业务逻辑**：它只建运行目录、用 `subprocess` 依次调用各节点脚本、
看退出码决定是否继续。

### 3.2 只跑某一个节点

```powershell
# 只跑节点 8（任务循环）
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.step8_run_task --run-dir <run-dir>

# 断点续跑：从节点 6 接着跑
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.main --resume --run-dir <run-dir> --from 6

# 只跑节点 6 到 7
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.main --run-dir <run-dir> --from 6 --to 7
```

### 3.3 主控参数

| 参数 | 说明 |
| --- | --- |
| `--dry-run` | 不点击、不等待、不清理 |
| `--from N` / `--to N` / `--only N` | 指定起止节点 |
| `--resume` | 沿用 `--run-dir` 或**最近一次**运行目录 |
| `--keep-going` | 某节失败后仍继续（调试用） |
| `--pre-clean` | 开始前强制清理残留进程 |
| `--show-cmd` | 打印每节的完整命令行（便于手工复现） |
| `--list` | 只列链条 |
| `--step-arg ARG` | 原样透传给每一个 step 的额外参数 |
| `--target LIST` | 目标程序，逗号分隔，任意多个：`ww` / `nte` / `zmd`（MaaEnd）/ `ww,nte` / `nte,ww` …。**省略**时跟随 `state.json` 的记录 |
| `--run-timeout SEC` | 整轮墙钟上限（默认 1800s = 半小时） |
| `--keep-game` | 到点收尾时**不关游戏** |
| `--no-watchdog` | 停用整轮时间上限 |

**`--target` 的取值来自 `orchestrator/targets.py`**（不再是硬编码的
`ww|nte|both`，加程序只要往 `orchestrator/programs.py` 的 `ALL` 里加一条）：

| 写法 | 结果 |
| --- | --- |
| `--target ww` / `--target nte` | 单个程序，不算串联 |
| `--target ww,nte` | 串联，**按书写顺序**跑（不是清单顺序 —— 想先跑 nte 就写 `nte,ww`） |
| `--target all` / `--target both` | 全部，按清单声明顺序（`both` 是 2026-10 的历史写法，永久保留） |
| 重复项 / 中文逗号 / `+` / 空格分隔 | 都接受，重复项去重并保留首次位置 |
| 未知 key（`--target xx`） | **立刻报错退出**，连 `--list` 也报（错误信息里列出全部已知 key） |
| `--target all,ww` | 报错：别名 `all`/`both` 不能和其他程序名混用 |

⚠️ **一个节点只能跑一个程序**：节点级命令行（`context.add_common_args`）拿到
`--target ww,nte` 会直接报错，而不是随便挑一个 —— 那个节点该操作谁是真的歧义。

**加第 3 个程序**（`foo`）要做的事：`orchestrator/programs.py` 的 `ALL` 里加一条
`Program(key="foo", display="ok-foo", ...)`；再同步 `gui/targets.py` 的 `FALLBACK`
（那是 GUI 的**第二处声明**，不同步界面会告警「清单漂移」，但仍以磁盘值为准）。
`main.py` / `targets.py` / GUI 的多选清单**都不用改** —— 它们全从 `ALL` 派生。

**`--target ww,nte` 串联**：按给定顺序**各跑一遍完整链条**，
不是把两个程序的节点混在一条链里。三个实现要点：

1. 两轮各用**子目录**（`<run-dir>/ww`、`<run-dir>/nte`）。共用目录的话
   两轮节点号完全相同（都叫 `step8.log`），**后一轮会覆盖前一轮**，
   事后分不清哪份日志属于哪个程序。
2. **一个程序失败不中断另一个**（用户裁定可无人值守）。退出码仍非 0 供脚本判断。
3. 每轮**各自独立计** 30 分钟上限，不是共享一个总上限。

```bash
# 串起来跑一遍（ok-ww 先，ok-nte 后）
python -m orchestrator.steps.main --target ww,nte

# 只看编排不碰真机
python -m orchestrator.steps.main --target ww,nte --dry-run --only 1
```

⚠️ **串联不是并发**：两程序沿用 INV-15 的独占前提，**串行**执行
（`all` / `both` 两个老写法等价于 `ww,nte`）。

另有**透传给特定节点**的参数（主控自己不做处理，只转发）：
`--skip-admin-check`（节点 1）、`--no-launch`（节点 2）、
`--only-locate` / `--freeze-seconds` / `--total-timeout`（节点 8）、
`--force-clean`（节点 9）。

---

## 4. 交接面：`state.json`

各节点**只**通过 `<run-dir>/state.json` 与 PNG 文件通信，
不共享 Python 对象、不共享内存 —— 所以任何一个节点换个进程跑，结果一样。

```
<run-dir>/
  state.json      各节点的结论（唯一交接面）
  chain.log       主控日志
  step1.log …     每个节点自己的日志（单独排查用）
  shots/          抓图落盘（**必须肉眼复核**）
```

`state.json` 的形状：

```json
{
  "run_dir": "...", "started_at": "...", "dry_run": false,
  "steps": {
    "6": {"name":"first_frame", "status":"ok", "elapsed":1.8,
          "data": {"width":1458, "height":800, "identity": {"score":0.47}},
          "shots": ["shots/001-first-frame.png"]}
  },
  "hwnd": 32966438, "pid": 46344,
  "frame": {"path":"shots/001-first-frame.png", "width":1458, "height":800},
  "result": "completed"
}
```

⚠️ **`hwnd` 只作记录，不作依据**。INV-14 要求「hwnd 不缓存，每次重新发现」
（每次运行都不同，实测出现过六个值）。所以每个要用窗口的节点都会先按标题正则
**重新发现**一次并以新值覆盖。

### 节点状态与退出码

| `status` | 退出码 | 含义 |
| --- | --- | --- |
| `ok` | 0 | 通过 |
| `skipped` | 0 | **按参数主动跳过**，链条继续 |
| `failed` | 3 | 校验失败/异常，链条停手 |
| `timeout` | 3 | 超时（节点 8） |
| （未捕获异常） | 2 | 环境/前提不成立 |

---

## 5. 排障工作流（**这是拆分的主要收益**）

假设主控跑到节点 6 失败：

```
[FAIL] 节点  6  first_frame   1.3s  身份校验失败（帧可能不是 ok-ww）
[主控] 节点 6 未通过 —— 链条在此停手
  => 修好代码后**只重跑这一节**：
     python -m orchestrator.steps.step6_first_frame --run-dir "..."
  => 全链续跑：
     python -m orchestrator.steps.main --resume --run-dir "..." --from 6
```

于是你可以：

1. **看抓图**：`<run-dir>/shots/001-first-frame.png` —— 只靠分数会漏掉
   「抓到别的窗口」，**必须肉眼复核**；
2. **改一份代码**：只打开 `step6_first_frame.py`；
3. **只重跑这一节**：秒级，前面的启动/等待**不用重来**。

### 离线调试：完全不碰程序

节点 6 与 8 支持**注入帧**，可以在 ok-ww 没跑的情况下反复验证识别链：

```powershell
# 用历史帧跑完整的校验链（尺寸 + 非全黑 + 身份）
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.step6_first_frame `
    --adopt-frame "probe\running-000.png" --new-run

# 只验证「导航 + 定位」链（不点击、不需要窗口）
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.step8_run_task `
    --adopt-frame "probe\running-000.png" --only-locate --offline
```

**为什么这很重要**：识别链的失败模式**大多是静默的**
（HANDOFF §9：一个从不报错的校验器等于没有校验器）。
用历史帧反复喂，是唯一可靠的验证方式。

### 手工接管某一节

```powershell
# 程序已在跑：直接指定 hwnd，跳过节点 2/4
& "D:\WORKs\Anaconda\python.exe" -m orchestrator.steps.step6_first_frame `
    --run-dir <run-dir> --adopt-hwnd 32966438
```

---

## 6. 实测记录（拆分后的验证）

拆出来的代码**逐节点实跑过**，不是只做了语法检查。

### 6.1 真实端到端（节点 1→2→4→5）

```
& python.exe -m orchestrator.steps.main --from 1 --to 5 --skip-admin-check

[SKIP] 节点  1  check_admin               0.4s  按参数跳过
[OK]   节点  2  launch                    0.6s  已启动 ok-ww.exe
[OK]   节点  4  wait_second_layer        74.9s  第二层就绪 hwnd=32966438
[OK]   节点  5  wait_ready               24.4s  就绪 1458x800
```

节点 4 实测 **74.9 秒**出现第二层 Qt 窗口
（`标题=[OK-WW v3.7.4 China  - OK-WW]`），与文档「约 21 秒」的差异是因为
**本次是首次启动且停在应用更新页**（文档已说明首次启动会更久，故给 300s 余量）。

### 6.2 节点 6 离线（识别链）

```
--adopt-frame "probe\running-000.png"     1875x1250   身份 score=1.0000  [OK]
```

### 6.3 节点 9 的路径白名单（防误杀）

```
将终止 pythonw.exe pid=46344  (E:\...\ok-ww\...\pythonw.exe)
跳过 pythonw.exe pid=66528 —— 路径不在 ok-ww 目录下：E:\...\ok-nte\...\pythonw.exe
```

**这一条验证了 Q3 的硬要求**：本机同时有 ok-nte 的 `pythonw.exe`，
按进程名扫会误杀；节点 9 按**可执行路径前缀**正确区分了两者。

### 6.4 负向对照（校验器真的会失败）

| 输入 | 期望 | 实测 |
| --- | --- | --- |
| 不存在的 run-dir 跑节点 7 | 报错并给出注入方法 | ✅ 退出码 2，提示 `先跑 step4，或 --adopt-hwnd` |
| 缺 `exit_notice` 资产 | 明确打印缺口 | ✅ 节点 8 打印「唯一的功能缺口」 |
| 未提权跑节点 9 | 拒绝而非静默 | ✅ `[跳过] 未提权，框架无力终止进程` |

---

## 7. 拆分**未能**解决的问题（如实列出）

拆分管的是「**代码怎么组织**」，不改变「**识别逻辑对不对**」。以下都是
**拆分前就存在**的问题，拆分只是让它们**更容易被定位**：

### 7.1 节点 6 在实跑中失败：身份校验 0.47

实跑时节点 6 报：

```
[INV-12] 身份校验失败：侧栏图标 score=0.4074 < 0.95
```

**已量化根因**（用同一份资产比对三帧）：

| 帧 | 尺寸 | score | 位置 |
| --- | --- | --- | --- |
| `probe/running-000.png`（任务页参考帧） | 1875x1250 | **1.0000** | (16,215) |
| 实跑帧（应用更新页，置前台前） | 1458x800 | 0.4718 | (145,13) |
| 实跑帧（应用更新页，置前台后） | 1458x800 | 0.4074 | (568,527) |

⇒ **校验器工作正常**，它正确地拒绝了一个「不是任务页、且几何不符」的帧。
原因是文档已记录的 **INV-4（出生尺寸）/ INV-39（窗口尺寸归一化）**：
侧栏资产的参考位置 `(16,215)` 是在 1822x1000 / 1875x1250 下实测的，
而实跑窗口是 **1458x800**。

**尚未实现**：README-ORCHESTRATOR §5 要求编排在抓帧前
**主动把窗口归一化到配置尺寸**（`window_size`）；`orchestrator/` 包里
**还没有这一步**。落地位置应是新节点（如 `step5b_normalize_size`），
放在节点 5 与 6 之间。

### 7.2 节点 6 抓到的是「应用更新页」而非任务页

实跑抓到的帧是 ok-ww 的**关于/应用更新页**（标题 `OK-WW v3.7.4 China`）。
这本身不算错 —— 导航是节点 8 的 `[8a]` 的职责。但节点 6 的
**身份校验把「不是任务页」也一并拒了**，导致链条进不到节点 8 去导航。

⇒ 身份校验（在不在 ok-ww）与页面校验（在不在任务页）**语义被混在一起**。
按 [IMPLEMENTATION-0.1.md](./docs/IMPLEMENTATION-0.1.md) §3.1，
身份校验本来是通过的（score=1.0000）—— 差异在于**窗口尺寸**，见 §7.1。

### 7.3 `exit_notice` 资产仍然缺失

**唯一的功能缺口**（文档一致记载）：横幅文案在「正常完成」与「等待状态」下
**完全相同**，唯一区分图元是通知「成功执行任务, 正在退出游戏和App!」。
资产未采集 ⇒ 节点 8 **无法判定「正常完成」，只能以超时收场**。

采集方法见 [assets.json](./orchestrator/assets.json)。

### 7.4 实跑需要管理员

节点 1 是**硬前置**：非提权会话杀不掉 ok-ww（实测 `Stop-Process` -> Access denied）。
`--skip-admin-check` 只跳过自检，**不会**让节点 9 具备终止能力。

---

## 8. 与旧版的关系

| 目录 | 状态 |
| --- | --- |
| [`legacy/code-old-orchestrator/`](./legacy/code-old-orchestrator/)（原 `probe/orchestrator.py` + `probe/targets.py`） | **旧版**（README §3 的 `--pre-clean` / `--only` 那套）。最近一次实跑判 `SUCCESS`（107s）。**已移入 `legacy/`**，见 [legacy/README.md](./legacy/README.md) |
| `orchestrator/` 包 | 重构版（九节点、`node1..node9` 命名）。**未改动** |
| `orchestrator/steps/` | **本链**：把上一个包的 `run()` 链条按节点拆开 |
| [`gui/`](./gui/) | **新增**：套在本链外面的两页 GUI（跑 / 改代码）。见 [GUI-README.md](./GUI-README.md) |

⚠️ 旧的 `Orchestrator.run()` 代码**完整保留在 `legacy/code-old-orchestrator/`**，
但**已不在 import 路径上**（`probe/` 下不再有这两个文件），需按
[legacy/README.md](./legacy/README.md) 的说明移回原位才能运行。
拆分与 GUI **没有删除任何原有代码**。

### 8.1 GUI 与节点代码的关系

[`gui/`](./gui/) 是**跳板**，不 import 任何节点模块：

| 交互 | 方式 |
| --- | --- |
| 读/改节点代码 | 直接读写 `steps/stepN_*.py`（第 2 页编辑器） |
| 运行 | 子进程 `python -m orchestrator.steps.main <args>` |
| 进度 | 轮询 `<run-dir>/state.json`（**不解析日志**） |
| 停止 | `taskkill /T /F` 整树终止 |

⚠️ **步骤清单在 `gui/chain.py` 里另有一份声明** —— 这是刻意的：节点文件语法
坏掉时 GUI 必须还能打开去修它。GUI 启动时会把它与 `steps/main.py` 的 `CHAIN`
比对，不一致就在界面上警告。**改链条时两处都要改。**

---

## 9. 不变量与本拆分的关系

拆分**不改变**任何一条不变量（INV-1..INV-52）。逐条对照：

| 不变量 | 拆分后如何保证 |
| --- | --- |
| INV-1 帧尺寸 == 窗口 rect | 节点 6，`capture.grab_frame` 原样调用 |
| INV-4 出生尺寸同源 | 节点 8 `[8b]`，仍打印警告 |
| INV-7 必须提权 | 节点 1，**硬前置** |
| INV-8 必须在前台 | 节点 7 + 节点 8 每次点击前重查 |
| INV-12 身份校验 | 节点 6，**每次抓帧都做** |
| INV-13 非全黑 | 节点 6 |
| INV-14 hwnd 不缓存 | `context.rediscover_hwnd`，每个用窗节点都重新发现 |
| INV-17 抓帧前校验在屏内 | 节点 6，`capture.grab_frame` 内部 |
| INV-19 按钮中心落在行内 | 节点 8 `[8b]` 交叉验证 |
| INV-22 最小化哨兵 | 节点 7 `ensure_foreground` |
| INV-23 目标坐标顶层判定 | 节点 8 `[8c]` `guarded_click` |
| INV-24 锚点联合唯一性 | 节点 8 `[8a]` `[8b]` |
| INV-30 证据不足不默认成功 | 节点 8 `[8e]`：三分终止行为 + 超时 |
| INV-42 目标间前台锁 | 节点 7 失败提示「先等 10 秒」 |

**新增的一条工程约束**（不是领域不变量）：
各节点**只通过 `state.json` 通信**，不得共享进程内对象 ——
这是「任意一环可独立替换」得以成立的前提。
