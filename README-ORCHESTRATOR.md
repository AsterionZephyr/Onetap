# 编排框架 · 使用手册

> **面向使用者与维护者**。本文回答：怎么跑、跑什么、出问题看哪里。
> 设计依据与实测证据见 [FRAMEWORK.md](./FRAMEWORK.md)（不变量 + §0.1 目标程序差异一览）、
> [COMPLETION-VERDICT.md](./COMPLETION-VERDICT.md)、[CLEANUP.md](./CLEANUP.md)。

---

## 1. 这是什么

按**顺序**启动 ok-ww 与 ok-nte，完成各自的日常任务，并**如实报告**每个程序的结果。

**核心原则**（全部来自实测教训）：

| 原则 | 含义 |
| --- | --- |
| **黑盒** | 不改两个程序的源码，只做窗口截屏 + 真实鼠标点击 |
| **真实光标** | 用 `SetCursorPos` + `SendInput`；**不用** PostMessage（UIPI 会拒绝） |
| **独占** | 同一时间只跑一个目标；开始前清理残留进程 |
| **如实报告** | 证据不足报 `UNKNOWN`，**绝不默认成功** |
| **不检查游戏状态** | 用户要求：直接启动程序并点击，游戏由用户自行准备 |

---

## 2. 环境

| 项 | 值 |
| --- | --- |
| **Python** | `D:\WORKs\Anaconda\python.exe`（3.13.9） |
| **依赖** | numpy 2.3.5、Pillow 12.0.0、pywin32 |
| **不可用** | cv2 / pyautogui / mss（**不要引入**） |
| **权限** | 需**管理员**（否则无法终止目标进程） |
| **屏幕** | 2560×1440 物理 |

⚠️ **不要用 `C:\Python314`** —— 它没有 numpy / Pillow。

---

## 3. 快速开始

```powershell
cd E:\TOOLS\ScriptsGames\Onetap\probe

# 完整串联（推荐）：ok-ww -> ok-nte
& "D:\WORKs\Anaconda\python.exe" orchestrator.py --pre-clean

# 只跑一个
& "D:\WORKs\Anaconda\python.exe" orchestrator.py --only ok-ww --pre-clean
& "D:\WORKs\Anaconda\python.exe" orchestrator.py --only ok-nte --pre-clean

# 空跑（只校验流程，不启动、不点击）
& "D:\WORKs\Anaconda\python.exe" orchestrator.py --dry-run
```

### 命令行参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--only NAME` | 无 | 只跑指定目标（`ok-ww` / `ok-nte`） |
| `--dry-run` | 关 | 不启动、不点击，只走校验逻辑 |
| `--pre-clean` | 关 | 开始前强制清理残留进程（**推荐**） |
| `--task-timeout N` | **1200** | 单个任务等待上限（秒） |
| `--no-cleanup` | 关 | 结束后不做兜底清理（调试用） |

### 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 全部目标判定为 `SUCCESS` |
| `1` | 有目标非 `SUCCESS`（`FAILED` / `TIMEOUT` / `UNKNOWN`） |

### 结果文件

每次运行写一份 JSON 到 `legacy/probe-investigation/orch-runs/orch-YYYYMMDD-HHMMSS.json`（**旧版编排器的记录，已移入 `legacy/`**；当前链条改用运行目录 + `state.json`）。

---

## 4. 判定语义（**必读**）

编排对每个目标给出四种终态之一：

| 终态 | 含义 | 是否算成功 |
| --- | --- | --- |
| `SUCCESS` | 日志判据确认任务完成 | ✅ |
| `FAILED` | 启动/校验/定位/置前台失败，或日志明确失败 | ❌ |
| `TIMEOUT` | 超过 `--task-timeout` 仍未完成 | ❌ |
| `UNKNOWN` | **证据不足** —— 进程退出了但没有完成证据 | ❌（**不默认成功**） |

⚠️ **`UNKNOWN` 是特性，不是 bug。** 它是防"假阳性"的最后一道闸门。
实测中我**两次**差点交付假阳性（详见 [COMPLETION-VERDICT.md](./COMPLETION-VERDICT.md) §6/§12）。

### 两个程序的判据**不同**

| | ok-ww | ok-nte |
| --- | --- | --- |
| 判据模块 | `ww_verdict.py` | `nte_verdict.py` |
| 依据 | 任务**阶段序列** | **终止标记** |
| 关键证据 | 到达 `check discarded echo` | `Successfully Executed Task, Exiting Game and App!` |
| 逐项结果 | 无 | ✅ success / failed / skipped |

**日志位置**（两者同名同结构，路径不同）：

```
ok-ww :  E:\TOOLS\ScriptsGames\ok-ww\data\apps\ok-ww\working\logs\ok-script.log
ok-nte:  E:\TOOLS\ScriptsGames\ok-nte\data\apps\ok-nte\working\logs\ok-script.log
```

⚠️ **只读"本次运行新增"的部分**（按文件字节偏移）。
不能"读全部日志再分段" —— 被外部强杀的运行不写 `ok:quit app`，会串味（INV-36/37）。

---

## 5. 编排流程

每个目标依次执行：

```
[1]     启动 exe
        等待第二层窗口（最多 180s；第一层会自动放行）
[2]     置前台 + 校验（重试 + AttachThreadInput + 验证）
[2a]    归一化窗口尺寸 -> 资产采集尺寸
        抓帧 + 尺寸校验 + 非全黑校验
[2b]    等待就绪（程序化 ☰ 连续 3 次命中）
[3]     身份校验（程序化 ☰）
[4]     定位动作元素
          不在任务页 -> 导航（点侧栏第 N 项）
          页面锚点 + 动作元素 双重确认
[5]     遮挡判定（顶层窗口必须是目标）-> 真实点击
[6]     验证已启动（行结构变化）
[7]     等待完成（轮询日志判据，最多 --task-timeout）
        兜底清理
```

### 关键设计：**归一化窗口尺寸**

程序的 UI **随窗口尺寸变化**，而它**会持久化窗口几何**，
所以每次启动的尺寸都可能不同（实测出现过 1458×800 / 1823×1000 / 1875×1250 /
2279×1250 / 2560×1400）。

⇒ 编排在抓帧前**主动把窗口设成配置的尺寸**（`window_size`），
使图像资产始终有效。这比"让锚点适应所有尺寸"可靠得多（INV-39）。

---

## 6. 图像资产

目录：`templates/`。元数据：`templates/assets.json`。

### 当前资产

| 文件 | 尺寸 | 用途 | 归属 | 采集版本 |
| --- | --- | --- | --- | --- |
| `2_ww_page.png` | 330×38 | **页面锚点**（日历图标 + 「每日任务」） | ok-ww | v3.7.3 |
| `2_ww.png` | 1823×42 | 「每日任务」整行（行结构扫描参考） | ok-ww | v3.7.3 |
| `3_ww_menu.png` | 21×18 | 身份锚点（☰）**回退用** | ok-ww | v3.7.3 |
| `1_ww.png` | 27×31 | 侧栏图标（**已不用于身份**） | ok-ww | — |
| `3_nte_daily.png` | 155×35 | **页面锚点**（首行「异象界域」） | ok-nte | v1.4.8 |
| `4_nte_menu.png` | 26×20 | 身份锚点（☰）**回退用** | ok-nte | v1.4.8 |
| `2_nte.png` | 103×46 | 旧版动作元素（**v1.4.8 起已弃用**，已移入 [`legacy/assets/`](./legacy/assets/)） | ok-nte | v1.4.7 |

> `templates/` 现只剩 6 张在用资产。已弃用的 `2_nte.png` 见 [legacy/assets/](./legacy/assets/)。

⚠️ **身份锚点实际不用模板**：编排主用**程序化检测 ☰**（见 §9.3），
`3_ww_menu.png` / `4_nte_menu.png` 仅作回退。


### 资产必须满足的条件

| 条件 | 说明 |
| --- | --- |
| **唯一** | 全帧匹配 ≥ `ACCEPT`(0.90) 的候选**恰好 1 个** |
| **自匹配 1.0000** | 模板必须能在自己的位置精确命中 —— 否则说明匹配器有 bug |
| **页面无关**（身份锚点） | 如 ☰，在任何页面都存在 |
| **含足够特征** | 见下方"切片禁忌" |

**切片禁忌**（实测踩过）：

| 反例 | 后果 |
| --- | --- |
| 只取「每日任务」四字 | 被「**多账号**每日任务」的**子串**命中 → 2 个候选 |
| 只取日历图标 | 与进度面板同款图标冲突 → 3 个候选 |
| 页面锚点单独使用 | 「关于」页曾假阳性 0.9373（INV-33）→ 必须**同时**确认动作元素 |

### 重新采集资产

```powershell
& "D:\WORKs\Anaconda\python.exe" refresh_assets.py
```

⚠️ **不要凭坐标手工裁剪** —— 实测连续 3 次裁错（把 ← 返回箭头当成 ☰）。
必须用**程序化特征检测**定位后裁剪（INV-34）：

- ☰：找"三条等距水平亮线"
- 按钮：找青色区域 / 白色描边块

---

## 7. 脚本结构

### 核心模块（**生产代码**）

| 文件 | 作用 |
| --- | --- |
| **`orchestrator.py`** | **主编排入口**（本文档的主角） |
| **`targets.py`** | **配置中心** —— 唯一"因程序而异"之处 |
| `ww_action.py` | 行结构扫描（定位「开始」按钮） |
| `ww_verdict.py` | ok-ww 终态判据 |
| `nte_verdict.py` | ok-nte 终态判据 |
| `cleanup.py` | 按**进程血缘**强制清理 |
| `capture.py` | 窗口发现 + `GetDC`/`BitBlt` 抓帧 |
| `template_probe.py` | `match_template`（归一化互相关） |
| `nte_main.py` | `all_hits`（唯一性检查） |
| `pngout.py` | 无依赖 PNG 写出（备用） |
| `refresh_assets.py` | 程序化重采资产 |

### 依赖关系

```
orchestrator.py
  ├── targets.py ──► nte_main.py, template_probe.py
  ├── capture.py ──► pngout.py
  ├── template_probe.py
  ├── cleanup.py
  ├── ww_action.py ──► targets.py
  ├── ww_verdict.py  (或 nte_verdict.py，由配置选择)
  └── nte_main.py
```

### 调查脚本（**一次性，非生产**）

其余 **50 个**脚本是开发期的**一次性调查工具**（`nte_sweep.py`、`page_map.py`、
`anchor_*`、`t4_*`、`q3_*`、`taskbar_*` 等）。它们保留作为**证据追溯**，
**不参与生产流程**，可以安全忽略。

（`probe/` 共 61 个 `.py`；核心 11 个，调查类 50 个。）

⚠️ 若要清理，**只删这些**；上表的核心模块不要动。

---

## 8. 配置（`targets.py`）

```python
TARGETS = {
    "ok-ww": {
        "exe": r"E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe",
        "cwd": r"E:\TOOLS\ScriptsGames\ok-ww",
        "title_regex": "OK-WW",
        "window_size": (1823, 1000),      # 资产采集尺寸，编排会归一化到此
        "nav_sidebar_index": 2,           # 侧栏第几项（0-based）= 任务页
        "nav_sidebar_y": 230,             # 仅回退参考
        "anchors": {
            "identity": <☰ 模板>,          # 页面无关
            "page":     <页面锚点>,
            "action":   None,             # None = 由行结构扫描得出
        },
        "state_fn": ww_state,             # 界面状态（仅记录，不裁决）
        "verdict_module": "ww_verdict",   # 终态判据模块
        "done_when": "process_gone",
    },
    "ok-nte": { ... "action_scan": "find_nte_action" ... },
}

ORDER = ["ok-ww", "ok-nte"]   # 用户指定的顺序
ACCEPT = 0.90                 # 匹配阈值
```

### 关键字段

| 字段 | 说明 |
| --- | --- |
| `window_size` | **必填**。编排会把窗口调整到此尺寸 |
| `nav_sidebar_index` | 比绝对 y 稳健（侧栏行距随窗口缩放） |
| `action: None` | 表示"动作元素由扫描得出"，配合 `action_scan` |
| `verdict_module` | 两个程序的判据**不同**，必须分开 |

### 阈值选择

| 分数 | 处理 |
| --- | --- |
| ≥ **0.90** | 接受 |
| 0.85 – 0.90 | 警告 |
| < 0.85 | 拒绝 |

⚠️ **不要设成 0.95** —— 实测会把布局有轻微偏移的**正确**页面误拒（0.9402）。

---

## 9. 注意事项（按重要性排序）

### 9.1 必须遵守

1. **以管理员运行** —— 否则清理阶段无法终止进程。
2. **程序会移动鼠标** —— ok-ww 有 `MouseResetTask`（日志 125 处 `move mouse back`）。
   编排点击后若依赖光标位置，需重新确认。
3. **不要硬编码 `hwnd`** —— 每次运行都不同（实测 ok-ww 出现过
   `9834000` / `198446142` / `55771756` / … 六个值）。
4. **不要硬编码窗口尺寸** —— 程序会持久化几何，每次都可能不同。
5. **每次抓帧都要做身份校验** —— 否则会一本正经地分析**别的程序**的画面
   （开发中实际发生过**两次**）。
6. **超时是必需的** —— 程序卡在等待条件时**永不退出**，无超时则整个编排死锁。

### 9.2 常见"良性"现象（**不要当故障**）

| 现象 | 真相 |
| --- | --- |
| `[WinError 5] 拒绝访问`（ok-ww 日志） | 目标进程**已经退出**，不是权限问题。首次尝试总是成功 |
| `GetCursorPos 拒绝访问` | ok-ww 自己的鼠标归位任务在提权环境下读光标被拒 |
| `MergeEchoTask Failed找不到对话框左侧按钮` | 已知无害 |
| 第一层 exe 自行退出 | **设计如此**（`Kill Launcher After Start`） |
| 游戏崩溃弹窗 | 用户说"不要管" |
| `TaskDisabledException` | 任务被中断；ok-nte 的单项失败**与本项目无关** |

### 9.3 已知的**等待态**

| 程序 | 特征 | 后果 |
| --- | --- | --- |
| ok-ww | 日志刷 `TaskExecutor:no frame available, skip remaining trigger tasks` | **永不完成**，等游戏起来；编排会 `TIMEOUT`/`UNKNOWN` |
| ok-ww | 界面提示 `请在大世界并在队伍中开始！` | 同上，计时器冻结 |

⇒ 这是**正常行为**，不是框架 bug。游戏未运行时必然如此。

### 9.4 目标间的前台锁

紧接上一个程序退出后启动下一个程序时，**置前台可能失败**
（实测 ok-nte 4 次尝试全败；单独启动则第 1 次成功）。

⇒ 编排已内置 `settle_between_targets(10)` 在目标间等待 10 秒（INV-42）。

---

## 10. 故障排查

| 症状 | 先看这里 |
| --- | --- |
| `身份校验失败` | 是否抓到了**别的程序**的窗口？看日志里的窗口标题 |
| `页面锚点未命中` | 窗口尺寸是否被归一化？看 `[2a]` 那行 |
| `动作元素定位失败` | 行结构扫描的阈值；程序 UI 是否改版 |
| `置前台失败` | 是否有别的窗口抢焦点；目标间等待是否够 |
| `TIMEOUT` | 游戏是否在运行？看程序日志有没有 `no frame available` |
| `UNKNOWN` | **正常**。日志里没有完成证据 —— 任务确实没跑完 |
| 程序升级后锚点失效 | 重采资产（`refresh_assets.py`） |

### 排查工具

```powershell
# 看窗口与进程现状
& "D:\WORKs\Anaconda\python.exe" cleanup.py

# 单看判据（不启动程序）
& "D:\WORKs\Anaconda\python.exe" ww_verdict.py
& "D:\WORKs\Anaconda\python.exe" nte_verdict.py

# 强制清理残留
& "D:\WORKs\Anaconda\python.exe" cleanup.py --do
```

---

## 11. 待办 / 已知问题

| 项 | 说明 |
| --- | --- |
| ~~ok-nte 执行了错误的任务~~ | ✅ **已澄清（归因更正）**：曾据一次观测判定"编排固定点第一行 → 只跑了「异象界域」"。**实测证伪** —— 一次完整运行的日志给出：<br>`success=['一咖舍','日常领取','影院约会','喷泉签到','异象家具','羁遇赠礼']`<br>`failed=['异象界域']  skipped=['异象追猎']`<br>⇒ **跑的是完整日常任务集合**，`异象界域` 只是**恰好失败**的那一项。<br>⚠️ **教训**：这是本项目第二次「**观测为真、归因错误**」（第一次是 INV-29） |
| **ok-nte 的「开始」语义** | 各行的「开始」触发的是**同一个日常计划**，不是"只跑这一行"。故行结构扫描取首行是**正确**做法 |
| **ok-nte 的导航索引** | `nav_sidebar_index=3` 按 v1.4.7 定；v1.4.8 实测可用（侧栏第 3 项，y≈229） |
| **资产与版本绑定** | 程序升级会使页面类资产过期（实测 v1.4.7→v1.4.8 后 `2_nte.png` 完全失效、`3_nte_daily.png` 从 1.0000 掉到 0.38）。`assets.json` 已记录版本，但编排**尚未做启动时校验** |
| **游戏进程遗留** | 超时后游戏可能仍在运行；当前 `kill_game=False`（默认不动） |
| **ok-ww 等待态检测** | 目前靠超时兜底；可解析 `no frame available` 提前判定"等游戏中" |
| **`match_template` 曾长期错误** | 旧的"粗步进 + 局部细化"会**漏掉真实峰**（自匹配只得 0.6086）。已改为 FFT 精确实现（自匹配 1.000000）。**若发现历史结论与此矛盾，以新实现为准** |



---

## 12. 相关文档

| 文档 | 内容 |
| --- | --- |
| [FRAMEWORK.md](./FRAMEWORK.md) | **不变量**与实测证据（**总纲**，含 §0.1 两程序差异一览） |
| [CONTEXT.md](./CONTEXT.md) | 术语表 |
| [COMPLETION-VERDICT.md](./COMPLETION-VERDICT.md) | 完成判据（Q1）与两次自纠 |
| [CLEANUP.md](./CLEANUP.md) | 清理策略（Q3） |
| [ORCHESTRATION.md](./ORCHESTRATION.md) | 编排实现记录 |
| [HANDOFF.md](./HANDOFF.md) | 早期交接书 |
| [docs/adr/0001-blackbox-real-cursor.md](./docs/adr/0001-blackbox-real-cursor.md) | 架构决策：黑盒 + 真实光标 |
