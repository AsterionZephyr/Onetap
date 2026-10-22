# 4. GUI 用 tkinter 同进程，否决浏览器 / Streamlit 类方案

日期：2026-10-06

## 状态

已接受。GUI 已按本决策实现并通过自检（[GUI.md](../GUI.md) §7）。

## 背景

需要给「节点代码化 + 可编辑 + 运行时显示当前节点」做一层图形界面：某个节点失败后，能当场改它的 `.py`、保存、只重跑这一个节点。先决问题不是「哪个 GUI 库好看」，而是**哪一层进程拥有窗口**。

三条实测环境约束框住了选型（均在 `D:\WORKs\Anaconda\python.exe` 3.13.9 上实测）：

- 目标程序都以 `requireAdministrator` 运行，框架**必须以管理员运行**（INV-7），否则连清理进程都会被拒；
- 本机屏幕 2560×1440、系统缩放 125%，操作前必须声明 **DPI 感知**；
- 项目有依赖洁癖（[`AGENTS.md`](../../AGENTS.md) 第 2 条：`cv2` / `pyautogui` / `mss` 不可用，不引入）。

## 决策

1. GUI 用标准库 **`tkinter` + `ttk`**，**与编排核心同进程**：入口以管理员启动，建窗口前先调 `win32.ensure_dpi_aware()`；主线程跑 Tk 主循环，worker 线程跑编排、经 `queue.Queue` 回传日志与节点事件。
2. **否决任何「浏览器持有 UI、控制逻辑在另一进程」的方案**：Streamlit、纯标准库 Web、FastAPI/Flask + 浏览器、Flet / NiceGUI / Gradio / pywebview 全部不采用。
3. 代码编辑器自绘：`tk.Text` + `tag_*` 实现行号、高亮、撤销、自动缩进；高亮只走**增量**，全量重打仅用于载入。
4. 自提权放在 `import tkinter` **之前**（`ShellExecuteW("runas")` 重启提权副本）；失败降级为横幅 + 跳过清理（[GUI.md](../GUI.md) §1.2）。

## 理由

### 1. DPI 感知是硬约束（决定性）

[`orchestrator/win32.py:102`](../../orchestrator/win32.py#L102) 的 `ensure_dpi_aware()` 调 `SetProcessDpiAwareness(2)`（`PROCESS_PER_MONITOR_DPI_AWARE`）。模块注释写明：必须在**任何抓帧或坐标换算之前**调用；调用后 `GetSystemMetrics(0/1)` 返回物理像素，与窗口 rect 同坐标系。实测：

```
BEFORE  GetSystemMetrics: (2048, 1152)   awareness = 0 (unaware)   ← 逻辑像素（缩放 125%）
AFTER   GetSystemMetrics: (2560, 1440)   awareness = 2             ← 物理像素
```

差 **512×288**。`win32.click()` 用 `screen_size()` 作归一化分母（[`win32.py:438`](../../orchestrator/win32.py#L438)）：`nx = int(x * 65535 / (sw - 1))` —— 分母错 512，点击必然偏移。

实测偏斜（目标 x=2000）：

| 上下文 | 分母 | 发送值 | 偏差 |
| --- | ---: | ---: | --- |
| 已声明 DPI 感知 | 2559 | 51219 | ✅ 正确 |
| 未声明（子进程默认） | 2047 | 64030 | ❌ **偏 12811（约 20%）** |

这是「点偏」类**静默失效**：不报错、不崩溃，只是点歪。两条硬性质（实测）：

- **逐进程，不继承**：父进程声明后，子进程回到 `(2048, 1152)`（实测 `PARENT: aware, screen = (2560, 1440)` / `CHILD unaware screen: 2048 1152`）；
- **一次性**：必须在窗口存在**之前**设置，窗口创建后不可改。

⇒ `ensure_dpi_aware()` 必须在**拥有窗口的同一个进程**里、**建窗之前**调用。浏览器方案的 UI 进程不是操作屏幕的进程，架构上无法满足。

tkinter 同进程已实测可行：

```
step1 screen: (2560, 1440)  →  step2 Tk screen: 2560 x 1440  (Tk 也看到物理像素，坐标系一致)
step2 Tk scaling: 1.6662   |  click normalization denominator: 2559 1439  ← 与 orchestrator 一致 ✅
```

### 2. 权限令牌

INV-7 要求框架本身以管理员运行。tkinter 方案里 GUI **就是**那个提权进程，令牌一致。浏览器方案里 `streamlit run` 若由普通终端启动，服务器进程未提权，再 `Popen` 提权子进程就**每次弹 UAC**。[`FRAMEWORK.md`](../FRAMEWORK.md) 的教训（见 [HISTORY.md](../HISTORY.md) B.1）是：`IsAdmin` 读的是**当前进程的令牌**，用户手动提权自己的终端**不会**让框架进程提权。这一条对浏览器方案是每天的摩擦，对 tkinter 是零成本。

### 3. 依赖体积与安装

| 库 | 状态 | 体积 |
| --- | --- | --- |
| `tkinter` | ✅ 可用（Tk 8.6.15） | **0 MB（随 Python 分发）** |
| `streamlit` | ⚠️ 已装 1.51.0 | 28.8 MB（+ pandas 62.8 / pyarrow 22.9 / altair 8.8 / tornado+watchdog 4.1） |
| PySide6 | ⚠️ 已装 6.9.2 | 29.8 MB（LGPL） |
| Flet / NiceGUI / Gradio / pywebview | ❌ 未装 | — |

⚠️ **「Streamlit 要下载 300–500MB」的说法不成立**：它和依赖链**已经装在项目所用的 Anaconda 环境里**，实测导入 0.77 秒。所以「依赖太重」**不是**否决它的正确理由。但「已经装了」≠「可以依赖」：那是环境巧合，不是项目依赖声明；写进项目就等于固化一个 28.8 MB + 约 100 MB 传递依赖的外部契约，而 tkinter 增量是 0。

### 4. 外网可达性实测纠错

| 通道 | 结果 |
| --- | --- |
| PowerShell `Invoke-WebRequest` | ❌ 全部失败（**含 baidu.com**）→ 是 PS 的 TLS 问题，**不是没网** |
| Python `urllib` | ✅ **HTTP 200 正常** |
| DNS 解析 | ✅ 正常 |

⇒ 这台机器**有外网**，「不能引 CDN」的理由不成立。但「用现成编辑器」的代价是实打实的：Monaco 最小 JS 集 **3624.0 KB**（loader 29.3 + editor.main 3388.1 + css 112.7 + nls 93.9），完整 dist 通常 5–10 MB，还得自己维护升级。

### 5. 自绘编辑器的性能真相

全量重打高亮是 **O(n²)**；增量只重打改动行 ±20 行的可视区，成本与文件大小无关：

| 行数 | 全量 | 增量 | 提速 |
| --- | ---: | ---: | ---: |
| 100 | 3.8 ms | — | — |
| 200 | 11.8 ms | — | — |
| 400 | 47.3 ms | 0.85 ms | 50× |
| 800 | 178.3 ms | 0.86 ms | 195× |
| 2000 | 1108 ms | 0.90 ms | 1851× |
| 8000 | 26918 ms | 0.96 ms | 28052× |

增量输出与全量**逐 tag 完全一致**（实测 `True`）。⇒ 「tkinter 编辑大文件会卡」是**朴素实现**的问题，不是 tkinter 的问题。GUI 里的正式实现实测 2000 行增量 8.11 ms（[GUI.md](../GUI.md) §7.1）。

## 后果

**正面**：同进程、同 DPI 上下文、同权限令牌，三条硬约束天然满足；**零新增依赖**，无端口、无浏览器、无 CDN；实时日志用 `after()` 增量 append，`PIL.ImageTk` 可直接显示帧。

**负面，且必须承担**：编辑器是**手写**的 —— 行号 / 高亮 / 保存 / 撤销 / 自动缩进已实现，查找替换需手写（`Text.search()` 是原语，约 30 行），括号匹配 / 缩进参考线需手写，自动完成 / 多光标 / 代码折叠 / minimap 需手写或放弃，跳转定义需手写（可用 `ast`）。高亮是**正则**而非解析器（多行字符串、f-string 嵌套按正则近似，**任何输入都不会抛异常**，刻意）；全量重打不可用，必须走增量。

## 替代方案

**Streamlit**。被否，决定性理由两条：

1. **浏览器持有 UI** ⇒ GUI 进程不是操作屏幕的进程，`ensure_dpi_aware()` 的「同进程 + 建窗前」无法满足；
2. `streamlit run` 默认**未提权**，编排要提权就得每次 `Popen` 一个弹 UAC 的子进程。

（次生问题：整页重跑模型与「运行中实时 tail 日志」冲突，`st.empty()` / `st.fragment` 均有卡顿；`streamlit-monaco` 还有回写时序坑。）

**浏览器前端 + 本地服务**（纯标准库 `ThreadingHTTPServer`，或 FastAPI/Flask）。被否，决定性理由：

1. 与 Streamlit **同一类架构冲突** —— UI 在浏览器，编排核心只能退化为 Web 服务器 `Popen` 的子进程，每次重新声明 DPI；
2. **权限令牌问题依旧**：服务器未提权 → 子进程要弹 UAC。

「零新依赖」救不了纯标准库版：它牺牲的是**架构正确性**，不只是好不好看；FastAPI/Flask 还额外新增依赖。

**PySide6**。被否：环境里已有（29.8 MB），但体积大、LGPL 与「不引入依赖」的风格不符；tkinter 已够用，将来若需要复杂编辑器再考虑。

**`streamlit-ace` / `streamlit-monaco`**。被否：在其上再叠依赖，且 Monaco 组件在 Streamlit 里有已知回写时序坑。

**Flet / NiceGUI / Gradio / pywebview**。被否：未安装，且全是「浏览器 + 跨进程」，同 Streamlit 的架构问题。

> 公平地说：如果本项目**不需要**真实光标点击（即 DPI 约束不存在），纯标准库 Web 会是很好的选择。**是 DPI 约束，而不是审美，决定了这个选型。**

## 复现本文的实测

```powershell
cd E:\TOOLS\ScriptsGames\Onetap
# DPI 感知的开关差异（before / after）
& "D:\WORKs\Anaconda\python.exe" -c "import sys;sys.path.insert(0,'.');from orchestrator import win32 as w;print('before',w.screen_size());w.ensure_dpi_aware();print('after',w.screen_size())"
# tkinter 与编排核心处于同一 DPI 上下文
& "D:\WORKs\Anaconda\python.exe" -c "import sys;sys.path.insert(0,'.');from orchestrator import win32 as w;w.ensure_dpi_aware();import tkinter;r=tkinter.Tk();r.withdraw();print(w.screen_size(), r.winfo_screenwidth(), r.winfo_screenheight());r.destroy()"
# Streamlit 依赖链导入耗时
& "D:\WORKs\Anaconda\python.exe" -c "import time;t=time.time();import streamlit,pandas,pyarrow,altair,tornado,watchdog;print('%.2fs'%(time.time()-t))"
# tkinter 编辑器的功能自检（7 项断言）
& "D:\WORKs\Anaconda\python.exe" -X utf8 probe\_probe_tk_editor.py --selftest
# 全量 vs 增量高亮
& "D:\WORKs\Anaconda\python.exe" -X utf8 probe\_probe_tk_incremental.py
# 外网可达性（注意 PS 的 TLS 会误报「没网」）
& "D:\WORKs\Anaconda\python.exe" -c "import urllib.request;print(urllib.request.urlopen('https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/package.json',timeout=10).status)"
```
