# Onetap — ok-ww / ok-nte / MaaEnd 黑盒编排

在**进程外**、以**真实光标**、**黑盒**地操作自动化程序完成任务，目前包括ok-ww、ok-nte、MaaEnd。
三个程序均为**他人项目**：本仓库只观察其窗口、只按图像定位、只发真实光标，**不改造其源码**。

> 术语以 [docs/CONTEXT.md](./docs/CONTEXT.md) 为准（窗口持有者、匹配锚点、动作前置关、完成帧、静默失效……）。
> 说话和写文档时用 CONTEXT 的词，不要另造同义词。

## 重要文档约定

**本文件只写新会话必须知道、否则会做错事的内容。** 排障经过、实测数据、选型理由
一律写进对应主题文件，不写在这里 —— 避免 AGENTS.md 重新膨胀成流水账。

## 目录

| 文件 / 目录                    | 内容                                                                                                                                                                                |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/`                    | **全部文档都在这里**（根目录只留本文件与 `README.md`）                                                                                                                                               |
| `docs/FRAMEWORK.md`        | **不变量（INV-*）+ 目标程序差异一览 + 链条结构**。断言冲突时以它为准                                                                                                                                         |
| `docs/HANDOFF.md`          | **实现交接书**：静默失效全表、十二条硬性规则、陷阱、模块划分、产物索引                                                                                                                                             |
| `docs/RUNBOOK.md`          | 怎么跑：GUI / 命令行参数、单节点重跑、续跑、排障                                                                                                                                                       |
| `docs/VERDICT.md`          | **完成判定**（三程序终态口径）+ 日志窗口 + **清理策略**                                                                                                                                                |
| `docs/GUI.md`              | GUI 手册与自检记录                                                                                                                                                                       |
| `docs/CONTEXT.md`          | **领域术语表**（说话和写文档用它的词，不要另造同义词）                                                                                                                                                     |
| `docs/HISTORY.md`          | 实测记录与历史（含 ok-ww 窗口事实记录附录）                                                                                                                                                         |
| `docs/FAULT-LOG.md`        | 故障流水账                                                                                                                                                                             |
| `docs/adr/`                | 决策记录（0001 黑盒真实光标、0002 锚点组合与联合唯一性、0003 每程序专项模块、0004 Tkinter 而非 Web、0005 节点链属于每个程序、0006 工作区目录契约、0007 文档分层与单一事实源）                                                                                    |
| `orchestrator/`            | **正式实现**：引擎（`steps/main.py` + `context.py` + `chain.py`）、共用节点（`steps/common/`）、每程序清单与专属节点（`apps/<key>/nodes/`）。**每个程序跑哪几节由它自己的 `NODES` 清单决定**，见 `docs/adr/0005`                   |
| `orchestrator/apps/`       | **每程序一个包**：`<key>/__init__.py`（定位 + 身份证据 + 终态判据）、`<key>/nodes/__init__.py`（**该程序自己的节点清单 `NODES`**）、`<key>/nodes/stepN_*.py`（专属节点）。**改某个程序只改这里**，见 `docs/adr/0003`、`docs/adr/0005` |
| `orchestrator/steps/`      | 引擎与**共用节点**：`main.py` 主控、`context.py` 节点契约、`chain.py` 清单读取 API、`common/` 共用骨架（节点 1/2/4/5/6/7/9，节点 8 是 `push.py`）。**这里不出现具体程序名**；程序差异经钩子参数传入                                       |
| `orchestrator/frameops.py` | 节点 8 的**程序无关**助手：`shot` / `frame_changed` / `finish` / `CLICK_*` 阈值（`apps/` 与 `steps/common/push.py` 都从这里取，谁都不 import 谁）                                                          |
| `probe/`                   | **一次性探测脚本**，是证据来源，不是产品代码；**79 个脚本的索引在 `probe/README.md`**，工作区契约门禁是同目录的 `probe/_check_workspace.py`                                                                                |
| `templates/`               | 图像资产 + `assets.json`（图像 + 比例位置 + 出生尺寸 + 用途）                                                                                                                                       |
| `logs/`                    | 运行日志与抓帧落盘（**入库忽略**；保留/清理策略见 `docs/VERDICT.md`）                                                                                                                                    |
| `legacy/`                  | 程序分节点运行前的历史遗物                                                                                                                                                                     |

## 动手前

1. **每个程序跑自己的一份节点链**（`--target ww|nte|zmd`）。链条 = `orchestrator/apps/<key>/nodes/__init__.py`
   里的 `NODES` 清单（`Node(sid, name, label, why, has_args, shared)`），主控/GUI **只按清单执行**；
   节点数量、编号、顺序随程序（ww/nte = 1,2,4,5,6,7,8,9，只有 8 专属；zmd 的 5/6/8 专属）。
   `python -X utf8 -m orchestrator.steps.main --list` 逐份打印；`--only/--from/--to` 的编号指
   **该程序自己的**编号，不在清单里的直接拒绝。为什么这么拆见 `docs/adr/0005`。
2. **串联顺序 = `orchestrator/programs.py:ALL` 的声明顺序 = MaaEnd → ok-ww → ok-nte**（用户裁定：
   MaaEnd 排第一，它出问题不影响后面两个）。加新程序**追加在末尾**：加一条 `Program` +
   `orchestrator/apps/<key>/__init__.py` + `nodes/__init__.py`，**不用改** `main.py` / `context.py` / GUI，
   但要同步 `gui/targets.py`。差异一览见 `docs/FRAMEWORK.md` §0.1。
3. **归属规则**：程序专属逻辑只改 `orchestrator/apps/<key>/`。**禁止跨程序分派** —— 专属节点不得 import
   别的程序的节点，共用节点里不得写 `if prog.key == ...`，差异只能经钩子参数传入（节点 5 `pre_ready`、
   节点 6 `pre_frame`/`identity`/`identity_hint`、节点 8 `push.run` 的 `navigate`/`locate`/`wait`/
   `before_click`/`locate_note`）。专属节点调 `context.run_step(..., chain_key=<key>)`，错配会被 `[!!]`
   拒绝（rc=2，不写 state.json）。`match`/`verdict` 只用共用内核；迁走的名字经共用层 `__getattr__`
   惰性取，所以**裸名字写在函数体内不会走垫片**（`docs/adr/0003`「阶段三的教训」）。
4. **MaaEnd 是单层程序**（`MaaEnd.exe` 自己持窗口，`class='Tauri Window'` 精确相等）且**跑完不立刻退出**
   （判据不依赖进程消失，只看 `zmd\debug\mxu-tauri.log`，见 `docs/VERDICT.md` §5）。

## 动手前三条硬指令

1. **改共用层之前先读 `docs/HANDOFF.md` §2**（`capture`/`input`/`window`/`state`/`frameops`/`steps/common` 都算共用层），
   改完跑 `docs/adr/0003` 的「共用层回归清单」（三程序都要回归）。§2 的每一条都有实测依据，
   违反即**静默出错** —— 不抛异常、不返回错误码，只给错误结果。
2. **动完代码必跑 `python -m pyflakes orchestrator gui`，再跑对应的 `probe/*_selfcheck.py` 或 `probe/_probe_gui2_selftest.py`**。
   两者互补：pyflakes 抓不到「裸名字在函数体内绕过了共用层的 `__getattr__` 垫片」，selfcheck 抓不到
   「改了阈值但没人重跑实测」。新加的行为要有探针覆盖，索引见 `probe/README.md`。
3. **Python 用 `D:\WORKs\Anaconda\python.exe`（3.13.9），必须提权运行**。
   可用库只有 Pillow / numpy / win32gui / win32api；三个目标程序都是 `requireAdministrator`，
   非提权会话连杀进程都会被拒。库的范围与原因见 `docs/HANDOFF.md` §1。

**规则正文只有一处**：操作红线与静默失效陷阱在 `docs/HANDOFF.md` §2，不变量在 `docs/FRAMEWORK.md` §1，
历史与故障在 `docs/HISTORY.md` / `docs/FAULT-LOG.md`。**本文件不复述规则正文**，只写「先读哪、跑什么」
（为什么这样分层见 `docs/adr/0007`）。

## 改 Markdown

**用 edit/write 工具，不要用 PowerShell 文本管道** —— 会破坏 UTF-8 编码（本仓库已发生过一次，583 字符损坏）。

## 已知非问题（不要浪费时间）

`MergeEchoTask Failed找不到对话框左侧按钮`；`pywintypes.error (5, 'GetCursorPos')`；
游戏崩溃；**第一层 exe 自行退出**（正常，不是崩溃）；ok-nte 侧栏无法展开；
多个 `pythonw` / `msedgewebview2`；`[WinError 5] Failed to terminate process`（多半是**已经退出了**）。
详见 `docs/HANDOFF.md` §4 与 `docs/VERDICT.md` §8。

## 文件权限（附加规则，优先级最高）

**即使处于完全权限（danger-full-access）下，未经用户明确允许，不得在本工作区之外创建或修改任何文件。**

- 特别地，**不得改动系统配置**：注册表、环境变量、系统服务、计划任务、
  hosts、代理与网络设置、防火墙、驱动、`Program Files`、`Windows`、用户 profile 下的配置文件等。
- 需要读工作区外的文件（如 `E:\TOOLS\ScriptsGames\ok-ww\`、目标程序日志）时，
  **只读**即可；要写就先说明意图并**取得用户同意**。
- 目标程序（ok-ww / ok-nte / 游戏）自身运行时写自己的日志与存档，属其正常行为；
  **不要替它写、也不要为了"修好"而改它的文件**。
- 例外仅限：用户当次明确指示要改的那个路径。
