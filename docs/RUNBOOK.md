# 运行手册

> 本文件回答：**怎么跑、怎么断点续跑、出问题先看哪里**。
> 不回答：判定语义（看 [VERDICT.md](./VERDICT.md)）、框架规范与不变量（看 [FRAMEWORK.md](./FRAMEWORK.md)）、界面操作（看 [GUI.md](./GUI.md)）。
> 术语以 [CONTEXT.md](./CONTEXT.md) 为准；实现禁忌见 [HANDOFF.md](./HANDOFF.md)，历史故障见 [FAULT-LOG.md](./FAULT-LOG.md)。

## 1. 环境与前提

| 项 | 要求 |
| --- | --- |
| 平台 | Windows（依赖 Win32 API + 屏幕抓图） |
| Python | 3.13.x；本机实测 `D:\WORKs\Anaconda\python.exe`（3.13.9） |
| 依赖 | Pillow、numpy、pywin32（win32gui / win32api） |
| 禁止引入 | `cv2`、`pyautogui`、`mss` —— 本机未安装。`C:\Python314` 四个库全无，不可用 |
| 权限 | **管理员（提权）**。三个目标程序都是 `requireAdministrator`，非提权会话连杀进程都会被拒 |

- **必须提权**：这是硬前置。`--skip-admin-check` 只跳过节点 1 的自检，**不会**让节点 9 获得终止能力（未提权时节点 9 会打印「跳过：未提权，框架无力终止进程」）。
- **独占式**（INV-15）：同一时间只跑一个目标程序；任务结束即清理相关进程。
- **游戏需在运行**：ok-ww 卡在等待状态时**永不退出**（计时器冻结）。没有游戏时节点 8 必然以超时 / 未决收场，这不是框架故障。
- 所有命令在**仓库根**执行。命令统一写作 `python -X utf8 -m ...`；若 `python` 不在 PATH，把前缀换成 PowerShell 的 `& "D:\WORKs\Anaconda\python.exe" -X utf8 ...`。

## 2. 一键跑完

链条**属于每个程序**：每个程序自己的清单 `orchestrator/apps/<key>/nodes/__init__.py` 决定跑哪几节。
`--list` 按程序逐份打印（当前三份都是 1、2、4、5、6、7、8、9，**没有节点 3** —— 实机复核证明
「跨过第一层」不存在，见 [window.py](../orchestrator/window.py) 模块说明）：

```text
zmd / ww / nte：1 提权检查 → 2 启动 → 4 等待窗口持有者 → 5 等待窗口就绪 → 6 抓首帧并校验
              → 7 置前台 → 8 任务循环 → 9 退出与清理
```

节点**数量、编号、顺序随程序**，不再要求套九个；MaaEnd 的节点 5/6 是专属节点（多一道自我更新闸门 /
先点掉更新弹窗）。为什么这么拆见 [ADR 0005](./adr/0005-per-program-node-chain.md)。

为什么拆：原先 `run()` 是 479 行一气呵成的链条，出错要打开一个大文件、从头顶重跑（1~2 分钟起），其他节点的状态也丢了。拆开后一次只开一份（1.5~18KB）、只重跑一份（秒级）；节点之间只通过 `state.json` 交接。**拆分不改变任何不变量**，INV-1..INV-42 全部保持，例如：INV-1 帧尺寸 == 窗口 rect → 节点 6 `capture.grab_frame`；INV-12 身份校验 → 节点 6 每次抓帧都做；INV-14 窗口句柄不缓存 → 每个用窗节点重新发现；INV-23 目标顶层判定 → 节点 8 [8c] `guarded_click`；INV-30 证据不足不默认成功 → 节点 8 [8e] 的终止行为与超时。

节点与文件的对照**按程序**：看 `--list` 或该程序清单的 `shared` 字段 ——
`shared=True` → `orchestrator/steps/common/<name>.py`，`shared=False` →
`orchestrator/apps/<key>/nodes/<name>.py`。当前三份清单的对照：

| 节点 | 名称 | ok-ww / ok-nte | MaaEnd（zmd） |
| --- | --- | --- | --- |
| 1 | 提权检查 | 共用 [common/step1_check_admin.py](../orchestrator/steps/common/step1_check_admin.py) | 同左 |
| 2 | 启动目标程序 | 共用 [common/step2_launch.py](../orchestrator/steps/common/step2_launch.py) | 同左 |
| 4 | 等待窗口持有者 | 共用 [common/step4_wait_second_layer.py](../orchestrator/steps/common/step4_wait_second_layer.py) | 同左 |
| 5 | 等待窗口就绪 | 共用 [common/step5_wait_ready.py](../orchestrator/steps/common/step5_wait_ready.py) | **专属** [zmd/nodes/step5_wait_ready.py](../orchestrator/apps/zmd/nodes/step5_wait_ready.py)（先等自我更新收敛，多 `--update-wait`） |
| 6 | 抓首帧 + 校验 + 身份 | 共用 [common/step6_first_frame.py](../orchestrator/steps/common/step6_first_frame.py) | **专属** [zmd/nodes/step6_first_frame.py](../orchestrator/apps/zmd/nodes/step6_first_frame.py)（先点掉更新弹窗；身份证据换成本程序） |
| 7 | 置前台 + 可用性校验 | 共用 [common/step7_foreground.py](../orchestrator/steps/common/step7_foreground.py) | 同左 |
| 8 | 任务循环（8a 导航 / 8b 定位 / 8c 点击 / 8d 验证 / 8e 等待） | **专属** [ww/nodes/step8_run_task.py](../orchestrator/apps/ww/nodes/step8_run_task.py)、[nte/nodes/step8_run_task.py](../orchestrator/apps/nte/nodes/step8_run_task.py) | **专属** [zmd/nodes/step8_run_task.py](../orchestrator/apps/zmd/nodes/step8_run_task.py) |
| 9 | 退出与清理 | 共用 [common/step9_cleanup.py](../orchestrator/steps/common/step9_cleanup.py) | 同左 |
| — | 主控 / 交接面 / 清单 API | [main.py](../orchestrator/steps/main.py) / [context.py](../orchestrator/steps/context.py) / [chain.py](../orchestrator/steps/chain.py) | 同左 |

常用命令：

```powershell
# 只校验、不点击、不等待、不清理
python -X utf8 -m orchestrator.steps.main --dry-run

# 真跑一个程序（先清残留，再走完整链条）
python -X utf8 -m orchestrator.steps.main --target ww --pre-clean

# 串联：ok-ww 之后跑 ok-nte
python -X utf8 -m orchestrator.steps.main --target ww,nte --pre-clean

# MaaEnd（单层程序）
python -X utf8 -m orchestrator.steps.main --target zmd --pre-clean

# 只跑节点 8（编号 = 该程序自己清单里的节点；省略 --target 时跟随 state.json）
python -X utf8 -m orchestrator.steps.main --only 8

# 从节点 6 接着跑
python -X utf8 -m orchestrator.steps.main --resume --from 6

# ⚠ --only/--from/--to 的编号指该程序自己的节点；不在该程序清单里的编号会当场被拒
python -X utf8 -m orchestrator.steps.main --list --target zmd   # 看 MaaEnd 自己的链条
```

GUI：双击 [launcher/gui.bat](../launcher/gui.bat)（自助请求提权）。GUI 是跳板，**不 import 任何节点模块**：
运行 = 子进程按**该程序自己的清单**调链条（编号与 label 也来自清单），进度 = 轮询 `state.json`，
停止 = 整树终止。细节见 [GUI.md](./GUI.md)。

## 3. 主控参数全表

| 参数 | 作用 | 备注 |
| --- | --- | --- |
| `--dry-run` | 只做校验与定位，不点击、不等待、不清理 | 也写进 `state.json` 的 `dry_run` |
| `--run-dir DIR` | 指定运行目录 | 省略时新建；`--resume` 时优先用它 |
| `--resume` | 沿用 `--run-dir` 或**最近一次**运行目录 | 不新建目录 |
| `--from N` / `--to N` / `--only N` | 从节点 N / 跑到节点 N / 只跑节点 N | N 必须是**该程序清单里有的**编号（当前 1,2,4,5,6,7,8,9；没有节点 3） |
| `--keep-going` | 某节失败后仍继续 | 调试用；退出码仍非 0 |
| `--pre-clean` | 开跑前强制清理**本次目标**的残留 | 实际调用该程序的共用节点 9：`orchestrator.steps.common.step9_cleanup --force` |
| `--list` | 只打印链条，不执行 | 拼错 `--target` 时也会当场报错 |
| `--show-cmd` | 打印每节的完整命令行 | 便于手工复现 |
| `--python EXE` | 用来跑各节点的解释器 | 默认当前解释器 |
| `--step-arg ARG` | 原样透传给**每一个** step | 可重复 |
| `--target LIST` | 目标程序，语义见下表 | 省略时跟随 `state.json`；新运行默认 ok-ww |
| `--run-timeout SEC` | 整轮墙钟上限 | 默认 `1800`（半小时）；`0` = 不限制 |
| `--keep-game` | 超时收尾时**保留**游戏，只关目标程序 | 默认按用户裁定：窗口和游戏都关 |
| `--no-watchdog` | 完全停用超时收尾 | 诊断用；挂住时要自己收拾现场 |

`--target` 取值语义（解析集中在 [targets.py](../orchestrator/targets.py)）：

| 写法 | 行为 |
| --- | --- |
| `ww` / `nte` / `zmd` | 单个程序，运行目录就是 `--run-dir` |
| `ww,nte` | 串联，**按书写顺序**（不是清单顺序）；各占子目录 `<run-dir>/ww`、`<run-dir>/nte` |
| `all` / `both` | 全部程序，按 [programs.py](../orchestrator/programs.py) 的 `ALL` 声明顺序 = **MaaEnd → ok-ww → ok-nte**；`both` 是 2026-10 的历史写法，永久保留 |
| 分隔符 | 英文逗号、中文逗号、`+`、空格都接受；重复项去重，保留首次位置 |
| 未知 key | 立刻报错，连 `--list` 也报；错误信息列出全部已知 key |
| `all,ww` | 报错：全量别名不可与具体 key 混用 |
| 单节点 | **一个节点只能跑一个程序**；把 `--target ww,nte` 传给单个节点会直接报错。共用节点用 `--target` 指明程序，专属节点由模块路径（`orchestrator.apps.<key>.nodes.*`）指明 |

透传给特定节点的参数（主控不解释，只转发）：

| 参数 | 目标节点 | 作用 |
| --- | --- | --- |
| `--skip-admin-check` | 1 | 跳过提权自检（诊断用；此后不会执行任何清理） |
| `--no-launch` | 2 | 不启动程序，假定已在运行 |
| `--only-locate` | 8 | 只跑导航 + 定位，不点击、不等待 |
| `--freeze-seconds S` | 8 | 计时器冻结多少秒判超时（默认 180） |
| `--total-timeout S` | 8 | 节点 8 兜底上限（默认 1800） |
| `--stall-grace S` | 8 | 执行器暂停后给它多少秒自行恢复，仍无进展才判 STALLED（默认 90） |
| `--force-clean` | 9 | 忽略结果，强制走清理路径 |

时间上限从高到低是三层：`--run-timeout`（整轮，默认 1800）→ `--total-timeout`（节点 8，默认 1800）→ `--freeze-seconds`（等待态冻结，默认 180）。到点由 watchdog 关目标窗口与游戏（`--keep-game` 保留游戏），必要时杀进程，并写 `state.json` 的 `watchdog` 字段。

## 4. 只跑一个节点 / 断点续跑 / 串联多目标

**单跑一个节点**（它自己解析运行目录与目标程序）。模块路径由该程序清单的 `shared` 决定：

```powershell
# 共用节点：模块在 steps/common/，用 --target 指明程序
python -X utf8 -m orchestrator.steps.common.step6_first_frame --run-dir "<run-dir>" --target ww

# 程序专属节点：程序已经在模块路径里，不用 --target
python -X utf8 -m orchestrator.apps.zmd.nodes.step8_run_task --run-dir "<run-dir>"
```

路径规则：`shared=True` → `orchestrator.steps.common.<name>`；`shared=False` →
`orchestrator.apps.<key>.nodes.<name>`。`--list` 只打节点名，要拿完整模组路径用
`python -X utf8 -c "from orchestrator.steps import chain; print(chain.module_of('ww','8'))"`。
程序专属节点会自检「本文件 + 本节点」是否属于该程序，错配打印 `[!!]` 并以 2 退出（不写 state.json）。

各节点也有自己的专属参数，例如 `step1 --skip-admin-check`、`step2 --no-launch`、`step4 --adopt-hwnd`、`step6 --adopt-frame`、`step7 --tries`、`step8 --only-locate`、`step9 --survey`。单节跑要求 `<run-dir>/state.json` 已存在；没有就**先跑节点 1**，或用 `--run-dir` 指一个已有的运行目录。

**断点续跑**：

```powershell
# 指定目录，从节点 6 接着跑
python -X utf8 -m orchestrator.steps.main --resume --run-dir "<run-dir>" --from 6

# 不指定目录：沿用最近一次运行
python -X utf8 -m orchestrator.steps.main --resume --from 6

# 只跑 6→7
python -X utf8 -m orchestrator.steps.main --run-dir "<run-dir>" --from 6 --to 7
```

修好代码后的标准动作（主控失败提示里就是这两条）：

```powershell
# 只重跑这一节（秒级）；<mod> = 该节点在清单里的模组路径，规则见 §4（共用 common / 专属 apps.<key>.nodes）
python -X utf8 -m <mod> --run-dir "<run-dir>"

# 全链续跑：从失败的那一节开始
python -X utf8 -m orchestrator.steps.main --resume --run-dir "<run-dir>" --from <N>
```

**串联多目标**（`--target ww,nte` / `all`）有三个要点：

1. **各占一个子目录**：`<run-dir>/ww`、`<run-dir>/nte`。若共用同一目录，两轮的 `step8.log` 会互相覆盖，事后分不清是哪个程序的。
2. **一个程序失败不中断另一个**（用户裁定：可无人值守）；全部跑完后退出码仍非 0。
3. **每轮各自独立计 30 分钟上限**；串联**不是并发**，沿用 INV-15 的独占前提，严格串行。

全部跑完会做一次**跨程序残留复检**：ok-nte 正常完成只关游戏本体 `HTGame.exe`，launcher `NTEGame.exe` 会残留（FAULT #31）。要清干净就再跑一次 `--pre-clean`，或对单一程序单跑共用节点 9：
`python -X utf8 -m orchestrator.steps.common.step9_cleanup --force`。

## 5. 交接面 state.json 与退出码

各节点是独立子进程，**只通过 `<run-dir>/state.json` 与 PNG 文件通信**，不共享 Python 对象或内存。运行目录内容：

```text
<run-dir>/
  state.json      唯一交接面
  chain.log       主控日志
  step1.log … step9.log
  shots/          抓图，排障时必须肉眼复核
```

`state.json` 形状（数值取自一次真实运行）：

```json
{
  "run_dir": "…\\logs\\runs\\run-20261015-203237",
  "started_at": "2026-10-15 20:32:37",
  "dry_run": false,
  "program": "ww",
  "steps": {
    "6": {
      "name": "first_frame",
      "status": "failed",
      "elapsed": 1.3,
      "data": {"width": 1458, "height": 800,
               "identity": {"score": 0.4700}},
      "shots": ["shots/001-first-frame.png"]
    }
  },
  "hwnd": 32966438,
  "pid": 46344,
  "frame": {"path": "shots/001-first-frame.png", "width": 1458, "height": 800},
  "result": "completed"
}
```

| 字段 | 含义 |
| --- | --- |
| `run_dir` / `started_at` / `dry_run` | 运行目录、开始时间、是否空跑 |
| `program` | 目标程序 key，**全链共享**；显式 `--target` 可覆盖 |
| `steps` | 节点号 → `{name, status, elapsed, data, shots}` |
| `hwnd` / `pid` | **只作记录，不作依据**（INV-14）。窗口句柄每次运行都不同，实测一次运行出现过六个值；每个用窗节点按标题正则重新发现并覆盖 |
| `frame` | 最近一次首帧：路径、尺寸、rect |
| `result` | 整轮结果；超时收尾时为 `timeout` |
| `watchdog` | 超时收尾明细：关了哪些窗口、杀了哪些进程 |
| `last_step` / `last_status` | 最后写入的节点号与状态 |

节点状态与退出码：

| 状态 | 退出码 | 含义 |
| --- | --- | --- |
| `ok` | 0 | 通过，链条继续 |
| `skipped` | 0 | 按参数主动跳过（如 `--skip-admin-check`），链条继续 |
| `failed` | 3 | 校验失败 / 抓帧被拦等，链条在此停手（`--keep-going` 可继续） |
| `timeout` | 3 | 节点 8 超时 |
| 未捕获异常 | 2 | 环境 / 前提不成立；例如运行目录不存在、缺 `state.json` |

主控汇总返回**最后一个失败节点的码**（可能是 2 或 3）；整轮被 watchdog 收尾时返回 3。`state.json` 的写盘是 `tmp + os.replace`，撞车会重试 12 次（FAULT #37）—— GUI 每 120ms 读一次，实测撞车率 7.8%（10233 次替换失败 794 次，错误码全是 5），因此偶发重试属正常。

## 6. 排障工作流

固定三步：

1. **看抓图**：`<run-dir>/shots/` 下最近一帧，**必须肉眼复核**。只靠数字会漏掉「抓到别的窗口」。
2. **看日志**：先 `chain.log` 找 `[FAIL]`，再看对应 `step<N>.log`；`state.json` 给的是结构化的状态与数据。
3. **只重跑这一节**（§4 的那两条命令），不要从头顶重跑。

常见失败：

| 症状 | 先看什么 | 处置 |
| --- | --- | --- |
| 身份校验失败 `score < 阈值` | `shots/001-first-frame.png` 是不是目标程序；ok-ww 的「节点选择」浮层是否盖住 ☰（FAULT #14）；抓帧前是否没置前台（FAULT #16） | 等浮层自行消失（节点 6 会重抓到 `--identity-timeout`，默认 120s）；不要用 `--skip-identity` 掩盖 |
| 页面锚点未命中 | 帧尺寸与窗口 rect；窗口是否被程序持久化成了别的几何（INV-39，见 §10） | 属已知限制；确认当前页是否是任务页 |
| 动作元素定位失败 | 程序 UI 是否改版；行结构扫描的阈值 | 升级后重采资产（INV-35） |
| 置前台失败（INV-42） | 是否紧接上一个程序退出 | 先等 10 秒再重跑节点 7，通常第 1 次就成功；或加大 `--tries`（默认 10） |
| `TIMEOUT` | 游戏是否在运行；ok-ww 日志有没有 `no frame available` | 先起游戏再重跑节点 8 |
| `UNKNOWN` | 日志里有没有完成证据 | 这是**特性**：没有证据就不判成功（INV-30），不是 bug |
| 程序升级后锚点失效 | 资产与版本（INV-35） | 重采资产；实测 v1.4.7→v1.4.8 后 `2_nte.png` 完全失效、`3_nte_daily.png` 从 1.0000 掉到 0.38 |

良性现象（**不要当故障**）：

| 现象 | 真相 |
| --- | --- |
| ok-ww 日志 `[WinError 5] 拒绝访问` | 目标进程已经退出，不是权限问题；首次尝试总是成功 |
| `GetCursorPos 拒绝访问` | ok-ww 自己的鼠标归位任务在提权下读光标被拒；本框架不用该 API |
| `MergeEchoTask Failed找不到对话框左侧按钮` | 已知无害 |
| 第一层 exe 自行退出 | 设计如此（Kill Launcher After Start），不是崩溃 |
| 游戏崩溃弹窗 | 用户裁定不要管 |
| `TaskDisabledException` | 任务被中断；ok-nte 单项失败与本项目无关 |

等待状态（**不是框架 bug**，游戏没起来时必然如此）：

| 现象 | 含义 | 结果 |
| --- | --- | --- |
| ok-ww 日志刷 `TaskExecutor:no frame available, skip remaining trigger tasks` | 游戏未运行 / 不在大世界，任务永不完成 | 框架最终判 `TIMEOUT` / `UNKNOWN` |
| ok-ww 界面提示「请在大世界并在队伍中开始！」 | 同上，计时器冻结 | 同上 |

## 7. 离线调试与手工接管

识别链的失败模式大多是**静默失效**，用历史帧反复喂才可靠；以下命令都不需要点击、不需要窗口（第一条要一张已落盘的帧）。

```powershell
# 节点 6（共用）：拿一张历史帧跑完整校验链（尺寸 + 非全黑 + 身份），--target 指明程序
python -X utf8 -m orchestrator.steps.common.step6_first_frame --adopt-frame "probe\running-000.png" --new-run --target ww

# 节点 8（程序专属）：只验证导航 + 定位链，不点击、不需要窗口
python -X utf8 -m orchestrator.apps.ww.nodes.step8_run_task --adopt-frame "probe\running-000.png" --only-locate --offline
```

**手工接管**（程序已经在跑，不想让框架再启动一次）：

```powershell
# 节点 2（共用）：只记录「已在运行」，不启动
python -X utf8 -m orchestrator.steps.common.step2_launch --run-dir "<run-dir>" --adopt-existing

# 节点 4（共用）：直接注入窗口句柄，跳过节点 2/4 的发现过程
python -X utf8 -m orchestrator.steps.common.step4_wait_second_layer --run-dir "<run-dir>" --adopt-hwnd 32966438
```

`--adopt-hwnd` 只有**节点 4** 有（节点 6 没有这个参数）。注入后从节点 5 或 6 继续即可；窗口句柄只用于本次记录，后续每个用窗节点仍会重新发现（INV-14）。

## 8. 加第 N 个程序要改哪里

加程序**不用改引擎**（[main.py](../orchestrator/steps/main.py) / [context.py](../orchestrator/steps/context.py) /
GUI 代码），只做这三步：

1. 在 [programs.py](../orchestrator/programs.py) 的 `ALL` **追加**一条 `Program(key=..., display=..., exe=..., ...)`。顺序即默认串联顺序：MaaEnd 必须排第一，`targets.self_check()` 有一条断言守着「第一个必须是 zmd」；新程序追加在末尾。
2. 新建 `orchestrator/apps/<key>/__init__.py`（该程序的定位 + 身份证据 + 终态判据，照 `apps/ww/__init__.py` 抄骨架），并在 [apps/__init__.py](../orchestrator/apps/__init__.py) 的 `ADAPTERS` 里注册。
3. 新建 `orchestrator/apps/<key>/nodes/__init__.py`：`NODES` 清单，逐条写清**这个程序跑哪几节**（共用节点也要写），元素是 `Node(sid, name, label, why, has_args, shared)`。需要专属节点就放 `orchestrator/apps/<key>/nodes/stepN_*.py`，文件末尾用 `context.run_step(..., chain_key="<key>")` 收尾。

再同步 [gui/targets.py](../gui/targets.py) 的 `FALLBACK`：那是 GUI 的**第二处**声明，不同步界面会报「清单漂移」（仍以磁盘上的 `programs.py` 为准）。

[targets.py](../orchestrator/targets.py) 与 GUI 的多选清单都从 `ALL` 派生。改共用层（`capture` / `input` / `window` / `state` / `frameops` / `steps/common`）必须三程序回归，清单见 [ADR 0003](./adr/0003-per-program-app-modules.md)。

## 9. 阈值与资产的注意点

- **匹配阈值取 0.90，不取 0.95**：≥0.90 接受、0.85–0.90 警告、<0.85 拒绝。设成 0.95 会把布局轻微偏移的**正确**页面误拒（实测 0.9402）。
- 图像资产必须同时满足：**唯一**（锚点唯一性：全帧 ≥0.90 的候选恰好 1 个）、**自匹配 1.0000**（否则匹配器有 bug）、**页面无关**（身份锚点如 ☰，任何页面都在）、**含足够特征**。
- **切片禁忌**（实测踩过）：
  - 只取「每日任务」四字 → 被「多账号每日任务」子串命中，2 个候选，最高分 0.9991 落在**错行**；
  - 只取日历图标 → 与进度面板同款图标冲突，3 个候选；
  - 页面锚点单独使用 → 「关于」页曾假阳性 0.9373（INV-33），必须同时确认动作元素。
  - 正确做法是「日历图标 + 每日任务四字」的**可见锚点组合**（ADR 0002）。不要凭坐标手工裁剪——实测连续 3 次裁错（把 ← 返回箭头当成 ☰），必须程序化特征检测后再裁（INV-34）。
- 点击前必须过**动作前置关**：页面锚点与动作元素同时命中才点。
- **资产与版本绑定**（INV-35）：程序升级会让页面类资产过期；`assets.json` 记录了版本，但编排**尚未**在启动时校验。
- **窗口尺寸影响分数**（INV-4 / INV-39）：锚点分数随窗口尺寸变化；`assets.json` 的「出生尺寸」只由 `check_born_size` 警告，编排**尚未**主动归一化窗口尺寸（详见 §10）。

## 10. 已知限制

| 限制 | 现状 | 依据 |
| --- | --- | --- |
| 管理员是硬前置 | **设计前提，已证实**（不是待办）。非提权连杀进程都被拒；`--skip-admin-check` 只跳自检 | INV-7 |
| 身份 / 锚点分数受窗口尺寸影响 | **尚未解决**。`orchestrator/` 里没有主动归一化窗口尺寸的代码；实跑窗口 1458x800 时侧栏图标 score=0.4074（同资产在 1875x1250 为 1.0000）。计划中的落地位置是节点 5 与 6 之间的 `step5b_normalize_size` | INV-39 / INV-4 |
| `exit_notice` 资产未采集 | **已解决**。完成帧的退出通知图元不再必需：ok-ww 与 ok-nte 同属 ok-script，收尾日志逐字相同，判据已改为日志（`verdict.ww_verdict`），该图像降为补充证据，采集可选 | FAULT #15 |
| 资产版本漂移 | **已知限制**：升级后需人工重采资产，启动时不校验 | INV-35 |
| 节点 6 只证明「在不在该程序」，不证明「在不在任务页」 | 导航是节点 8 [8a] 的职责；看到应用更新页 / 别的页面时看节点 8 的重定位 | 设计分工 |
| `UNKNOWN` / `STALLED` 需要人判 | `UNKNOWN` 是特性（证据不足不默认成功）；`STALLED` 是执行器暂停后的有界等待（默认 90s） | INV-30 / FAULT #30 |
| 串联时的前台锁 | **已证实**：紧接上一程序退出后置前台可能失败，编排目前没有显式目标间等待；节点 7 失败先等 10 秒再重跑 | INV-42 |
| 跨程序残留 | ok-nte 正常完成会把 launcher `NTEGame.exe` 留在后台，靠收尾的跨程序复检报告出来，不自动杀 | FAULT #31 |

旧版编排器（`--only ok-ww`、`--pre-clean` 写 `orch-runs/` 那套）在 [legacy/code-old-orchestrator/](../legacy/code-old-orchestrator/)，已不在 import 路径上，不要按旧文档的命令跑。
