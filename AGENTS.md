# Onetap — ok-ww / ok-nte / MaaEnd 黑盒编排

在**进程外**、以**真实光标**、**黑盒**地操作 ok-ww、ok-nte、MaaEnd 完成日常任务。
三个程序均为**他人项目**：本仓库只观察其窗口、只按图像定位、只发真实光标，**不改造其源码**。

> 术语以 [docs/CONTEXT.md](./docs/CONTEXT.md) 为准（窗口持有者、匹配锚点、动作前置关、完成帧、静默失效……）。
> 说话和写文档时用 CONTEXT 的词，不要另造同义词。

## 重要文档约定

**本文件只写新会话必须知道、否则会做错事的内容。** 排障经过、实测数据、选型理由
一律写进对应主题文件，不写在这里 —— 避免 AGENTS.md 重新膨胀成流水账。

## 目录

| 文件 / 目录 | 内容 |
| --- | --- |
| `docs/` | **全部文档都在这里**（根目录只留本文件与 `README.md`） |
| `docs/FRAMEWORK.md` | **不变量（INV-*）+ 目标程序差异一览 + 链条结构**。断言冲突时以它为准 |
| `docs/HANDOFF.md` | **实现交接书**：静默失效全表、十二条硬性规则、陷阱、模块划分、产物索引 |
| `docs/RUNBOOK.md` | 怎么跑：GUI / 命令行参数、单节点重跑、续跑、排障 |
| `docs/VERDICT.md` | **完成判定**（三程序终态口径）+ 日志窗口 + **清理策略** |
| `docs/GUI.md` | GUI 手册与自检记录 |
| `docs/CONTEXT.md` | **领域术语表**（说话和写文档用它的词，不要另造同义词） |
| `docs/HISTORY.md` | 实测记录与历史（含 ok-ww 窗口事实记录附录） |
| `docs/FAULT-LOG.md` | 故障流水账 |
| `docs/adr/` | 决策记录（0001 黑盒真实光标、0002 锚点组合与联合唯一性、0003 每程序专项模块、0004 Tkinter 而非 Web、0005 节点链属于每个程序、0006 工作区目录契约） |
| `orchestrator/` | **正式实现**：引擎（`steps/main.py` + `context.py` + `chain.py`）、共用节点（`steps/common/`）、每程序清单与专属节点（`apps/<key>/nodes/`）。**每个程序跑哪几节由它自己的 `NODES` 清单决定**，见 `docs/adr/0005` |
| `orchestrator/apps/` | **每程序一个包**：`<key>/__init__.py`（定位 + 身份证据 + 终态判据）、`<key>/nodes/__init__.py`（**该程序自己的节点清单 `NODES`**）、`<key>/nodes/stepN_*.py`（专属节点）。**改某个程序只改这里**，见 `docs/adr/0003`、`docs/adr/0005` |
| `orchestrator/steps/` | 引擎与**共用节点**：`main.py` 主控、`context.py` 节点契约、`chain.py` 清单读取 API、`common/` 共用骨架（节点 1/2/4/5/6/7/9，节点 8 是 `push.py`）。**这里不出现具体程序名**；程序差异经钩子参数传入 |
| `orchestrator/frameops.py` | 节点 8 的**程序无关**助手：`shot` / `frame_changed` / `finish` / `CLICK_*` 阈值（`apps/` 与 `steps/common/push.py` 都从这里取，谁都不 import 谁） |
| `probe/` | **一次性探测脚本**，是证据来源，不是产品代码；**79 个脚本的索引在 `probe/README.md`**，工作区契约门禁是同目录的 `probe/_check_workspace.py` |
| `templates/` | 图像资产 + `assets.json`（图像 + 比例位置 + 出生尺寸 + 用途） |
| `logs/` | 运行日志与抓帧落盘（**入库忽略**；保留/清理策略见 `docs/VERDICT.md`） |

## 动手前

0. **每个程序跑自己的一份节点链**（`--target ww|nte|zmd`，`orchestrator/programs.py:ALL` 是唯一来源）。
   链条 = `orchestrator/apps/<key>/nodes/__init__.py` 里的 `NODES` 清单
   （`Node(sid, name, label, why, has_args, shared)`），主控/GUI **只按清单执行**；
   **节点数量、编号、顺序随程序**（当前 ww/nte = 1,2,4,5,6,7,8,9，只有 8 专属；
   zmd = 1,2,4,5(专属)、6(专属)、7、8(专属)、9）。`python -X utf8 -m orchestrator.steps.main --list`
   按程序逐份打印链条（顺序 = `ALL`）；`--only/--from/--to` 的编号指**该程序自己的**节点编号，
   不在该程序清单里的编号直接拒绝。为什么这么拆见 `docs/adr/0005`。
   ⚠️ **串联执行顺序 = `ALL` 的声明顺序 = MaaEnd → ok-ww → ok-nte**（用户裁定）：MaaEnd 必须排第一，
   它出问题不影响后面两个应用（`run_multi` 任一轮失败仍继续下一轮）。加新程序**追加在末尾**，
   `targets.self_check()` 有一条断言守着「第一个必须是 zmd」。
   差异一览见 `docs/FRAMEWORK.md` §0.1；**加第 N 个程序 = 加一条 `Program`（`programs.py`）+
   `orchestrator/apps/<key>/__init__.py`（定位/判据）+ `orchestrator/apps/<key>/nodes/__init__.py`
   （清单，+ 需要的专属节点文件）**；**不用改 `main.py` / `context.py` / GUI 代码**。
   GUI 自己的目标列表在 `gui/targets.py`（解析 `programs.py`，读不到时用 FALLBACK），加程序要同步它。
   ⚠️ **MaaEnd 是单层程序**（`MaaEnd.exe` 自己持窗口，`class='Tauri Window'` 精确相等），
   且**跑完不立刻退出**（判据不依赖进程消失，只看 `zmd\debug\mxu-tauri.log`，见 `docs/VERDICT.md` §5）。
   ⚠️ **归属规则**：改某个程序的逻辑 → 只改 `orchestrator/apps/<key>/`；
   改共用层（`capture`/`input`/`window`/`state`/`frameops`/`steps/common`）→ **必须三程序回归**，
   清单在 `docs/adr/0003`「共用层回归清单」。**禁止跨程序分派**：程序专属节点**不得** import 别的
   程序的节点（`orchestrator.apps.<other>.nodes.*`），共用节点里也**不得**写 `if prog.key == ...` ——
   共用节点不认识具体程序，差异只能经钩子参数传入（节点 5 `pre_ready`、节点 6 `pre_frame`/
   `identity`/`identity_hint`、节点 8 `push.run` 的 `navigate`/`locate`/`wait`/`before_click`/
   `locate_note`）。程序专属节点调 `context.run_step(..., chain_key=<key>)`，程序与节点错配会被
   `[!!]` 拒绝（rc=2，且不写 state.json）。对 `match`/`verdict` 只用共用内核，已迁走的名字经共用层
   `__getattr__` 垫片惰性取。搬完代码**必跑 `python -m pyflakes orchestrator`**：为什么要跑见
   `docs/adr/0003`「阶段三的教训」（裸名字在函数体内不会走 PEP 562 的 `__getattr__`）。
1. **改这块代码前读 `docs/HANDOFF.md` 的「必须遵守的约束」**（§2）。那里每一条都有实测依据，
   违反即产生**静默错误** —— 不抛异常、不返回错误码，只给错误结果。
2. **Python 用 `D:\WORKs\Anaconda\python.exe`（3.13.9）**。
   可用：**Pillow、numpy、win32gui、win32api**；
   **不可用：cv2、pyautogui、mss** —— 未安装，**不要引入**。
   `C:\Python314` 四个库全无，**不可用**。
3. **必须提权运行**：三个程序都是 `requireAdministrator`，非提权会话连杀进程都会被拒。

## 会静默出错的地方（最重要）

这些失效**不报错**。必须主动校验，见 `docs/HANDOFF.md` §2.1 全表：

- **帧尺寸 ≠ 窗口 rect** → 点偏；**帧全黑** → 白算；**抓帧坐标越界** → 静默返回全黑帧
- **窗口被遮挡 / 抓到别的窗口** → 点空或分析错画面 ⇒ 每次抓帧后都要**身份校验**
- **锚点不唯一** → 匹配到同款图标；**子串匹配也会歧义**（「每日任务」被「多账号每日任务」命中）
- **点击落在遮挡窗口上** → 操作了别的程序 ⇒ 用 `WindowFromPoint` 做**目标顶层判定**
- **界面状态改变排版** → 坐标漂移 ⇒ **每次重新定位，绝不缓存**
- **全屏游戏期间抓帧** → 抓到的是游戏的像素，且**所有不变量都通过** ⇒ 静默分析错画面
- **帧坐标当 client 坐标用** → 点偏 8px；**跨运行借日志信号** → 假成功（MaaEnd 两条，见 `docs/HANDOFF.md` §2.1 第 12~14 条）

## 硬性规则（摘要）

1. **窗口尺寸会变**（实测 1200×800 至 1875×1250 等），**每次操作前重读 rect**。
2. **`hwnd` 每次运行都不同**，**不得写入配置或资产**。
3. **用标题正则发现窗口**（`OK-WW.*- OK-WW` 标题里有**两个空格**），不可精确相等。
4. **匹配阈值取 0.90，不取 0.95** —— 布局偏移会让正确页面降到 0.9402。
5. **置前台用 `SetForegroundWindow` 并每次验证**（单次调用不可靠，前台锁会挡）；
   **不要点任务栏**。窗口拉不到前台时，**真实鼠标点击窗口体**能拿到激活。
6. **不要依赖 `PrintWindow`** —— 对 Qt 自绘窗口返回**全黑**，只能屏幕抓图。
7. **判断 Win32 成败只看返回值** —— `GetLastError` 可能是无关调用的残留（实测 203）。
8. **提权下 `GetCursorPos 拒绝访问` 是良性的**，本框架不用该 API，无条件忽略。
9. **页面级元素必须配页面锚点** —— ok-nte 的「开始」在 3 个页面出现。
10. **超时是必需的** —— ok-ww 卡在**等待状态**时**永不退出**，无超时则整个编排死锁。
11. **证据不足时报 UNKNOWN，绝不默认成功**（INV-30）。
    「回到空闲态」有两种原因（真完成 / 失败回落），**按钮形态无法区分**。
12. **日志判据必须带时间戳基线闸** —— 程序会清日志/追加写，只按字节偏移会借到上一次运行的完成信号。
13. **等待阶段不要抓帧** —— 目标程序被全屏游戏盖住时，抓到的帧是游戏的像素且能通过全部不变量校验。

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
