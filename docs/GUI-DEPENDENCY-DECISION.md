# GUI 依赖选型调研（GUI Dependency Decision）

> **结论先行：不要用 Streamlit。用 `tkinter` + `ttk`（标准库）。**
> 决定性理由不是"依赖洁癖"，而是一条**实测硬约束**：`ensure_dpi_aware()` 必须
> 在**拥有窗口的同一个进程**里、且**在窗口创建之前**调用，而 Streamlit 把 GUI
> 放在**浏览器**里、把控制逻辑放在**另一个进程**里 —— 架构上无法满足。
> 证据见 §3。实测脚本与输出见 §3.3。

本文回答：为「节点代码化 + 可编辑 + 运行时显示节点名」的 GUI，最应该用什么依赖库。

相关：[FRAMEWORK.md](../FRAMEWORK.md)（不变量）、[CONTEXT.md](../CONTEXT.md)（术语）、
[README-ORCHESTRATOR.md](../README-ORCHESTRATOR.md)（使用手册）、
[docs/adr/0001-blackbox-real-cursor.md](./adr/0001-blackbox-real-cursor.md)。

---

## 1. 结论

| 方案 | 裁定 | 理由 |
| --- | --- | --- |
| **`tkinter` + `ttk`** | ✅ **采用** | 标准库，**零新增依赖**；与应用同进程，满足 DPI 硬约束；`Text` 组件天然支持行号/高亮/滚动；可嵌 `PIL.ImageTk` 直接显示帧。**可写性已实测**（§5.4） |
| Streamlit | ❌ **否决** | 见 §3：跨进程 + 浏览器，**架构上无法满足 DPI 硬约束**；且重跑模型与"运行中实时日志"冲突 |
| (a) 纯标准库 Web（`ThreadingHTTPServer` + 浏览器） | ❌ **否决** | **零依赖这点成立**，但同样是"浏览器持有 UI"，撞上 §3 同一条 DPI 硬约束（§5.4.5）。见 §5.4 完整对比 |
| (c) FastAPI / Flask + 浏览器 | ❌ 否决 | 同上架构问题 **+** 新增依赖，两条都占 |
| PySide6 | ❌ 否决 | 环境里**已有**（29.8 MB），但体积大、许可证（LGPL）与"不引入依赖"风格不符；tkinter 已够用。**若将来需要复杂编辑器再考虑** |
| `streamlit-ace` / `streamlit-monaco` | ❌ 否决 | 在 Streamlit 之上再叠依赖；且 Monaco 组件在 Streamlit 里有已知回写时序坑 |
| Flet / NiceGUI / Gradio / pywebview | ❌ 否决 | **未安装**，且全是"浏览器 + 跨进程"，同 Streamlit 的架构问题 |

**一句话**：这个项目要的不是"一个好看的网页 GUI"，而是**一个能安全按真实光标点屏幕的控制台** ——
GUI 必须和编排核心**同进程、同 DPI 上下文、同权限令牌**。这三点把浏览器类方案全部排除。

---

## 2. 环境事实（实测，非推断）

在 `D:\WORKs\Anaconda\python.exe`（3.13.9）上实测：

| 库 | 状态 | 体积 |
| --- | --- | --- |
| `tkinter` | ✅ 可用（Tk 8.6.15） | **0 MB（随 Python 分发）** |
| numpy | ✅ 2.3.5 | 40.3 MB |
| Pillow | ✅ 12.0.0 | 3.1 MB |
| pywin32 | ✅ | 19.6 MB |
| **streamlit** | ⚠️ **已装 1.51.0** | **28.8 MB** |
| pandas | ⚠️ 已装 2.3.3 | 62.8 MB |
| pyarrow | ⚠️ 已装 21.0.0 | 22.9 MB |
| altair | ⚠️ 已装 5.5.0 | 8.8 MB |
| tornado / watchdog | ⚠️ 已装 | 4.1 MB |
| PySide6 | ⚠️ 已装 6.9.2 | 29.8 MB |
| Flet / NiceGUI / Gradio / pywebview | ❌ 未装 | — |

### 2.1 对另一 agent「Streamlit 要下载 300–500MB」说法的更正

**该说法不成立** —— `streamlit` 及其依赖链（pandas / pyarrow / altair / tornado /
watchdog）**已经装在项目所用的 Anaconda 环境里了**。实测导入耗时 **0.77 秒**。

⇒ 所以"依赖太重"**不是**否决 Streamlit 的正确理由。正确理由是 §3 的架构冲突。

⚠️ 但要注意：**"已经装了"不等于"可以依赖"**。`HANDOFF.md` §1 明确列
"不可用：cv2 / pyautogui / mss"，`README-ORCHESTRATOR.md` §2 重申"依赖洁癖是本项目的风格"。
Anaconda 基础环境里恰好有这些包，**是环境巧合，不是项目依赖声明**。
把 `import streamlit` 写进项目，就等于把一个 **28.8 MB + 约 100 MB 传递依赖**的
外部契约固化下来 —— 而 tkinter 的增量是 **0**。

---

## 3. 决定性理由：DPI 感知是**硬**约束

### 3.1 事实

`orchestrator/win32.py` 的 `ensure_dpi_aware()`：

```python
ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
```

它的模块注释写明：「必须在**任何抓帧或坐标换算之前**调用。调用后
`GetSystemMetrics(0/1)` 返回**物理像素**（本机 2560×1440），与窗口 rect 处于同一坐标系。」

### 3.2 实测：不调用会怎样

```
=== BEFORE ensure_dpi_aware ===
GetSystemMetrics: (2048, 1152)          ← 逻辑像素（缩放 125%）
  awareness = 0 (unaware)
=== AFTER ensure_dpi_aware ===
GetSystemMetrics: (2560, 1440)          ← 物理像素
  awareness = 2
```

⇒ 差 **512×288 像素**。而 `win32.click()` 用 `GetSystemMetrics` 算归一化分母：

```python
sw, sh = screen_size()
nx = int(x * 65535 / (sw - 1))     # ← 分母错 512，点击必然偏移
```

**实测的偏斜量**（目标 x=2000）：

| 上下文 | 分母 | 发送值 | 偏差 |
| --- | --- | --- | --- |
| 已声明 DPI 感知 | 2559 | 51219 | ✅ 正确 |
| 未声明（子进程默认） | 2047 | 64030 | ❌ **偏 12811（约 20%）** |

这正是 `HANDOFF.md` §2.1 第 1 条「帧尺寸 ≠ 窗口 rect → **点偏**」的同类失效：
**不报错、不崩溃，只是点歪。**

### 3.3 DPI 感知的两条硬性质（这是否决 Streamlit 的核心）

我用实测确认了这两条：

**(a) 逐进程，不继承。** 父进程声明了，**子进程不会继承**：

```
PARENT: aware, screen = (2560, 1440)
CHILD  unaware screen: 2048 1152        ← 子进程回到逻辑像素
```

**(b) 一次性，窗口创建后不可改。** 必须在窗口存在**之前**设置。

### 3.4 为什么这否决了 Streamlit

Streamlit 的进程模型是：

```
[streamlit run gui.py]   ← 这个进程只是 Web 服务器
        ↓ HTTP / WebSocket
   [用户的浏览器]        ← 真正的 UI 在这里
```

- UI 在**浏览器**里 ⇒ GUI 进程根本不是操作屏幕的那个进程；
- 编排逻辑若跑在 Streamlit 进程里 ⇒ 它必须**自己**调 `ensure_dpi_aware()`，
  而该进程同时还在跑 Tornado/WebSocket 服务、watchdog 文件监视等多线程组件，
  **DPI 上下文与窗口创建时序无法保证**；
- 若编排逻辑跑在子进程里 ⇒ 每次都要重新声明 DPI（可做，但等于承认
  "GUI 与操盘手不在同一上下文"），且 §3.5 的权限问题依旧。

**对比 tkinter**：实测证明**同进程完全可行** ——

```
step1 screen: (2560, 1440)        ← 先声明 DPI 感知
step2 Tk screen: 2560 x 1440      ← Tk 也看到物理像素，坐标系一致
step2 Tk scaling: 1.6662
click normalization denominator: 2559 1439   ← 与 orchestrator 一致 ✅
```

⇒ **tkinter 与编排核心天然同进程、同坐标系、同 DPI 上下文。**

### 3.5 附带理由：权限令牌

`INV-7` 是硬前置：框架**必须以管理员运行**，否则杀不掉 ok-ww（未提权 → Access denied）。

- **tkinter**：GUI 就是那个提权进程，令牌一致。
- **Streamlit**：`streamlit run` 若由普通终端启动，服务器进程**未提权**；
  再指望它去 `Popen` 一个提权子进程 → 每次弹 UAC。而 `FRAMEWORK.md` §7.1
  的实测教训正是：「`IsAdmin` 读的是**当前进程的令牌**，用户手动提权自己的终端
  **不会**让框架进程提权；**必须是宿主本身以管理员启动**」。

⇒ 这一条对 Streamlit 是**每天都会遇到的摩擦**，对 tkinter 是**零成本**。

---

## 4. 逐条回应另一 agent 的 Streamlit 顾虑

它的顾虑**都成立**，但真正的结论应该是"**别用 Streamlit**"，而不是"用了要付这些代价"：

| 它的顾虑 | 核实结果 |
| --- | --- |
| 依赖链 300–500MB | ❌ **不准确**：环境里已装，实测导入 0.77s。**但**"已装 ≠ 该依赖"（§2.1） |
| 代码编辑器只能靠 `st.text_area`（无高亮/行号） | ✅ 成立。而 tkinter 的 `Text` + `tag_*` 可**无依赖**实现行号、高亮、撤销 |
| 整页重跑模型，实时 tail 日志要用 `st.empty()` + 循环 | ✅ 成立。tkinter 用 `widget.after()` 事件循环，增量 append 日志**零卡顿** |
| `st.fragment(run_every=...)` 对流式日志有卡顿 | ✅ 成立。同上，tkinter 无此问题 |
| 端口自动选端口 | ✅ 成立。tkinter 无端口概念 |
| Monaco 组件回写值有时序坑 | ✅ 成立。**这是反对 `streamlit-monaco` 的独立理由** |

⇒ 六条里**五条**都是"Streamlit 的架构代价"。当所有顾虑都指向同一个根因时，
正解是**换掉根因**，而不是接受这些代价。

---

## 5. 建议的 GUI 形态

### 5.1 架构（关键：**同进程**）

```
gui.py  (以管理员启动，唯一进程)
  ├─ 启动时: win32.ensure_dpi_aware()      ← 先在主线程声明，早于任何窗口
  ├─ 主线程: tkinter 主循环 (Tk root)       ← UI
  └─ 工作线程: 调用 orchestrator             ← 不阻塞 UI
        └─ 通过 queue.Queue 把日志/节点事件送回主线程
```

**这不是可选的设计品味，而是被 §3 强制的**：DPI 声明与窗口创建必须在同一进程。

### 5.2 对应你提的六条设计

| 你的要求 | tkinter 实现 |
| --- | --- |
| 节点代码化：一节点一文件 | `Text` 组件加载/保存 `.py` 文件；节点清单由目录扫描得出 |
| 新建代码目录 + git | GUI 只把**该目录**当作可编辑根；`git init` 由你手动或一个按钮执行 |
| GUI 只暴露这一层可编辑 | 文件选择器锁定在节点目录内（路径校验：拒绝 `..`） |
| 运行时显示节点名 | 日志回调里解析节点事件 → 写入顶部状态栏 + 列表高亮 |
| GUI 代码与节点代码分开 | `gui/` 与 `nodes/` 分目录（与 `orchestrator/` 并列） |
| 未提权警告 | 启动即 `win32.is_admin()`；不满足则**顶部常驻红条**（Q10 的 (b) 降级路径） |

### 5.3 为什么 tkinter 特别适合"帧预览"

项目反复强调「**抓图必须落盘供肉眼复核**」（HANDOFF §10.5）——
只用数字会漏掉"抓到别的窗口"。tkinter 可以直接用 `PIL.ImageTk` 把帧显示在面板里，
**不需要启动浏览器、不需要落盘再找文件**。这是 Streamlit 做不到的顺手。

---

## 5.4 「tkinter 做编辑器又丑又别扭」—— 实测复核

该断言**不成立**。我写了一个**可运行的** tkinter 代码编辑器
（[docs/_probe_tk_editor.py](./_probe_tk_editor.py)，约 230 行，**零第三方依赖**），
并用自检脚本逐项验证（`python docs/_probe_tk_editor.py --selftest`）：

```
=== tkinter 代码编辑器自检 ===
1. 高亮 6 行源码耗时           : 0.06 ms
2. 各类高亮命中数              : {'kw': 3, 'str': 1, 'comment': 1, 'num': 1, 'def': 1}
3. 行号槽行数                  : 7 (Text 报告 7 行)  内容='1\n2\n3\n4\n5\n6\n7'
4. 撤销可用 (undo=True)        : True
5. 回车自动缩进                : '    '
6. 保存往返一致                : True
7. 大文件 600 行高亮耗时       : 74.1 ms

全部自检通过
```

⇒ 另一 agent 说的「要高亮、要行号、要保存按钮」**全部已实测可做**，
且**没有引入任何依赖**。

### 5.4.1 但它的顾虑里有一条**是真的**：全量高亮会卡

实测全量重打高亮 **O(n²)**：

| 行数 | 全量高亮 | 判定 |
| --- | --- | --- |
| 100 | 3.8 ms | 流畅 |
| 200 | 11.8 ms | 流畅 |
| 400 | 47.3 ms | 可接受 |
| 800 | 178.3 ms | **不可用** |
| 2000 | 1108 ms | **不可用** |

**这是 tkinter 编辑器的真问题** —— 朴素的"每键全量重打"在 400 行以上打字发涩。

### 5.4.2 对策（已实测）：增量高亮 = 常数时间

只重打改动行 ±20 行的可视区（[docs/_probe_tk_incremental.py](./_probe_tk_incremental.py)）：

| 行数 | 全量 | 增量 | 提速 |
| --- | --- | --- | --- |
| 400 | 42.5 ms | **0.85 ms** | 50× |
| 800 | 167.4 ms | **0.86 ms** | 195× |
| 2000 | 1660.8 ms | **0.90 ms** | 1851× |
| 8000 | 26918 ms | **0.96 ms** | 28052× |

**关键**：增量成本**与文件大小无关**（~0.9 ms 恒定），且输出与全量
**逐 tag 完全一致**（实测 `一致: True`）。

⇒ 那个"不可用"是**朴素实现的问题，不是 tkinter 的问题**，且有常数时间的解。

### 5.4.3 真正需要自己写的东西（诚实清单）

浏览器方案（若 vendor 一个真编辑器）白拿、而 tkinter 要手写的：

| 功能 | 状态 |
| --- | --- |
| 行号 / 高亮 / 保存 / 撤销 / 自动缩进 | ✅ **已实测实现**（§5.4） |
| 查找替换 | 需手写；`Text.search()` 是原语，约 30 行 |
| 括号匹配 / 缩进参考线 | 需手写；tag 系统可做 |
| 自动完成 / 多光标 / 代码折叠 / minimap | **需手写或放弃** |
| 跳转到定义 | 需手写（可用 `ast` 模块） |

⚠️ **这张表是 tkinter 的真实代价**，不能否认。但要与 §5.4.4 的成本对比。

### 5.4.4 关于「外网可达性未知」—— 实测已澄清

另一 agent 假设"外网可达性未知，所以不能引 CDN"。实测结果**分两种情况**：

| 通道 | 结果 |
| --- | --- |
| PowerShell `Invoke-WebRequest` | ❌ 全部失败（**含 baidu.com**）→ PS 的 TLS 有问题，**不是没网** |
| Python `urllib` | ✅ **HTTP 200 正常** |
| DNS 解析 | ✅ 正常 |

⇒ 这台机器**有外网**。所以"不能引 CDN"的理由**不成立**，**但** vendor 的代价是实打实的：

```
loader.js              29.3 KB
editor.main.js       3388.1 KB
editor.main.css       112.7 KB
editor.main.nls.js     93.9 KB
-----------------------------
最小 JS 集            3624.0 KB   (完整 dist 含 language workers 通常 5-10 MB)
```

⇒ 要用"真编辑器"，得往一个依赖洁癖的仓库里**塞 3.6–10 MB 的 vendored JS**
（还得自己维护升级）。与 tkinter 的 0 字节相比，trade-off 并不一边倒。

### 5.4.5 但仍有一条**架构级理由**否决浏览器方案

无论 (a) 纯标准库 Web 还是 (c) FastAPI+浏览器，**都是"浏览器持有 UI"**，
因此**都撞上 §3 的 DPI 硬约束**：

- UI 进程 ≠ 操作屏幕的进程；
- `ensure_dpi_aware()` 必须在**拥有窗口的进程**、**窗口创建前**调用；
- 浏览器方案下，编排核心只能退化为"由 Web 服务器 `Popen` 的子进程"，
  每次都要重新声明 DPI，且 §3.5 的**权限令牌**问题依旧
  （服务器未提权 → 子进程要弹 UAC）。

⇒ **(a) 与 (c) 在本项目的核心约束下是同一类方案，差别只在依赖多寡** ——
所以"零新依赖"并不构成选 (a) 的理由，因为 (a) 牺牲的是**架构正确性**，
而不只是"好不好看"。

### 5.4.6 结论

| 维度 | tkinter | (a) 标准库 Web | 评 |
| --- | --- | --- | --- |
| 新增依赖 | **0** | 0 | 平 |
| DPI 硬约束（§3） | ✅ 同进程满足 | ❌ 架构上不满足 | **tkinter 胜（决定性）** |
| 权限令牌 | ✅ 一致 | ❌ 需 UAC 跳转 | **tkinter 胜** |
| 编辑器功能 | 够用（行号/高亮/撤销/保存已实测） | 需 vendor 3.6–10MB JS 才更好 | tkinter 略逊，代价可接受 |
| 实时日志 | `after()` 增量 append，零卡顿 | WebSocket/轮询 | tkinter 胜 |
| 帧预览 | `PIL.ImageTk` 直接显示 | 需 base64 编码传输 | tkinter 胜 |
| 需手写的编辑器功能 | 查找替换等（§5.4.3） | 白拿（若 vendor） | Web 胜 |

**⇒ 维持结论：用 tkinter。** 它的"丑"是**可控的实现工作量**，
而 Web 方案的问题是**不可回避的架构冲突**。

⚠️ 公平地说：如果本项目**不需要**真实光标点击（即 §3 的 DPI 约束不存在），
那么 (a) 会是很好的选择。**是 DPI 约束，而不是审美，决定了这个选型。**

---

## 6. 需要你裁决的一点

另一 agent 提到的矛盾我确认存在，但与 GUI 选型无关，列出供你一次裁定：

- **Q10**：它按 (c)「检测提权 + 一键 UAC 自重启，拒绝则降级为警告横幅」实现。
- 你先前说过「可以添加未提权警告」（听起来是 (b) 纯警告）。
- ⚠️ 注意 `FRAMEWORK.md` §7.1 的实测教训：**必须宿主本身以管理员启动**，
  "一键 UAC 自重启"在 Streamlit 架构下才需要；在 **tkinter 同进程架构**下，
  更简单的做法是**启动脚本用 `Start-Process -Verb RunAs` 拉起来**，
  进程内只做 `is_admin()` 检测 + 横幅。⇒ 建议 **(b) 为主，(c) 作为启动脚本的一行**。

> **落地结果（后续更新）**：最终选了 **(c) 进程内自提权**，即 `gui/__main__.py`
> 在 `import tkinter` **之前**调 `ShellExecuteW("runas")` 重启提权副本；
> 被拒 / 失败时**降级为 (b)**（横幅 + 节点 1 跳过）。见 `gui/elevate.py`。
>
> 这里当时判断"tkinter 同进程架构下自重启没必要"，理由是**会先闪一个无权限窗口**。
> 该顾虑成立，但解法很简单：**把提权放在 import tkinter 之前**，窗口就永远不会
> 被建出来。真正的代价是三个静默陷阱（`ShellExecuteW` 谎报成功、lpParameters
> 含 exe、自有参数放在 `-m` 之前），已在 GUI-README §2 记录。

---

## 8. 附：本次实测脚本

| 文件 | 用途 |
| --- | --- |
| [_probe_tk_editor.py](./_probe_tk_editor.py) | **可运行的** tkinter 代码编辑器（行号 + 高亮 + 撤销 + 自动缩进 + 保存）。`--selftest` 跑 7 项断言 |
| [_probe_tk_incremental.py](./_probe_tk_incremental.py) | 全量 vs 增量高亮的成本对比 + 逐 tag 正确性核对 |
| [_probe_tk_bench.py](./_probe_tk_bench.py) | 全量高亮随文件规模的增长曲线 |

⚠️ 这三个是**调研用探针**，与 `probe/` 下的一次性调查脚本同类，**不参与生产流程**。
正式实现时 `_probe_tk_editor.py` 可作为 GUI 编辑器组件的起点。

---

## 9. 复现本文的实测

```powershell
cd E:\TOOLS\ScriptsGames\Onetap

# DPI 感知的开关差异
& "D:\WORKs\Anaconda\python.exe" -c "import ctypes,sys;sys.path.insert(0,'.');from orchestrator import win32 as w;print('before',w.screen_size());w.ensure_dpi_aware();print('after',w.screen_size())"

# tkinter 与编排核心同 DPI 上下文
& "D:\WORKs\Anaconda\python.exe" -c "import sys;sys.path.insert(0,'.');from orchestrator import win32 as w;w.ensure_dpi_aware();import tkinter;r=tkinter.Tk();r.withdraw();print(w.screen_size(), r.winfo_screenwidth(), r.winfo_screenheight());r.destroy()"

# Streamlit 依赖链导入耗时
& "D:\WORKs\Anaconda\python.exe" -c "import time;t=time.time();import streamlit,pandas,pyarrow,altair,tornado,watchdog;print('%.2fs'%(time.time()-t))"

# tkinter 编辑器的功能自检（7 项断言）
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_tk_editor.py --selftest

# 全量 vs 增量高亮
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_tk_incremental.py

# 外网可达性（注意 PS 的 TLS 会误报"没网"）
& "D:\WORKs\Anaconda\python.exe" -c "import urllib.request;print(urllib.request.urlopen('https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/package.json',timeout=10).status)"
```
