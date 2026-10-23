# 实现交接书：ok-ww / ok-nte / MaaEnd 黑盒编排（+ FOS 只启动不操作）

> **读者：接手的 agent。** 你不需要重读全部探测脚本，但**必须**读完本文的「必须遵守的约束」。
> 详细依据见 [FRAMEWORK.md](./FRAMEWORK.md)（不变量 + 目标程序差异一览；实测过程在 [HISTORY.md](./HISTORY.md)）。
> 术语以 [CONTEXT.md](./CONTEXT.md) 为准。

---

## 0. 一句话目标

在**进程外**、以**真实光标**、**黑盒**地操作 ok-ww、ok-nte、MaaEnd：
启动 → 导航到任务页 → 点「开始」→ 等待任务完成 → 确认终态（前两个看进程退出，MaaEnd 看日志）。

**三个操作型程序均已端到端验证可行**（ok-ww：[HISTORY A.8](./HISTORY.md)；ok-nte 与 MaaEnd：FRAMEWORK §0.1 与 [HISTORY A.9-A.13](./HISTORY.md)）。

**第 4 个程序 FOS（`E:\TOOLS\ScriptsGames\MPA\FOS.exe`）只启动、不操作**：用户裁定它自己会退出并
清理干净，全程不需要识别与操作，**也不要研究它的内部逻辑**。链条 4 节（1 提权 → 2 启动 →
3 等它自己退出 → 9 清理），详见 [FRAMEWORK.md](./FRAMEWORK.md) §0.1.3 与 [VERDICT.md](./VERDICT.md) §2.1。

**最终目标是按顺序启动这些程序完成任务**。默认顺序 = MaaEnd → ok-ww → ok-nte → FOS
（= `programs.ALL` 的声明顺序），**但顺序可任意调整**：实际顺序 = `--target` 的书写顺序，
GUI 的 ↑/↓ 改的就是它（见 [GUI.md](./GUI.md) §2.1、[RUNBOOK.md](./RUNBOOK.md) §4）。

## 1. 环境（实测确定，不要改）

| 项 | 值 |
| --- | --- |
| Python | **`D:\WORKs\Anaconda\python.exe`**（3.13.9） |
| 可用库 | **Pillow 12.0.0、numpy 2.3.5、win32gui、win32api** |
| **不可用** | cv2、pyautogui、mss（**未安装，不要引入**） |
| 系统 Python | `C:\Python314` —— **四个库全无，不可用** |
| ok-ww 可执行 | `E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe` |
| ok-nte 可执行 | `E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe` |
| MaaEnd 可执行 | `E:\TOOLS\ScriptsGames\zmd\MaaEnd.exe`（单层程序，日志在 `zmd\debug\mxu-tauri.log`） |
| FOS 可执行 | `E:\TOOLS\ScriptsGames\MPA\FOS.exe`（单文件 PyInstaller，**只启动 + 等它自己退出**，无识别无操作） |
| 本机屏幕 | 2560×1440 物理 |
| **必须提权运行** | 三个操作型程序都是 `requireAdministrator`；非提权会话连杀进程都会被拒（FOS 是否要求提权**未验证**，节点 1 仍先查提权） |
| 远程软件 | GameViewer 在运行（会改缩放；**不要依赖固定分辨率**） |

**抓图**：`ctypes` + `BitBlt`（见 `probe/capture.py`）。
**匹配**：numpy 归一化互相关（见 `probe/template_probe.py` 的 `match_template`）。
**输入**：`SetCursorPos` + `SendInput`（参考实现见 `legacy/probe-investigation/run_daily2.py`）。

---

## 2. 必须遵守的约束（每条都有实测依据，违反即产生静默错误）

### 2.1 会静默出错的地方（最重要）

这些失效**不抛异常、不返回错误码**，只给错误结果。**必须主动校验**。共 18 条：1~11 来自 ok-ww / ok-nte 首轮；12~16、18 由 MaaEnd 接入暴露；17 由 ok-ww 自我更新暴露。

| # | 陷阱 | 后果 | 对策 |
| --- | --- | --- | --- |
| 1 | 帧尺寸 ≠ 窗口 rect | **点偏** | 抓帧后比对；不等即停手 |
| 2 | 窗口被遮挡 / 抓到别的窗口 | **点空**或分析错画面 | **身份校验** + 内容校验 |
| 3 | 帧全黑 | 白算 | 均值亮度过低即停手 |
| 4 | 抓帧坐标越界 | **静默返回全黑帧** | 抓前校验坐标在屏内 |
| 5 | 模板空白区不设约束 | 匹配到**同构空行**（实测 0.85 假阳性） | 只用有鉴别力的锚点 |
| 6 | 锚点不唯一 | 匹配到**同款图标**（实测差 0.006；ok-nte 侧栏有**两个 1.0000**） | **唯一性检查** |
| 7 | 置前台返回 True 但窗口最小化 | 操作无效 | 校验 rect ≠ `-32000` |
| 8 | 点击落在遮挡窗口上 | 操作了**别的程序** | `WindowFromPoint` 顶层判定 |
| 9 | 界面状态改变排版 | 坐标漂移 | **每次重新定位，不缓存** |
| 10 | `GetLastError` 有残留值 | 误判成败 | **只看返回值** |
| 11 | **同一按钮出现在多页** | 在错误的页面上点击 | **页面锚点 + 元素锚点**（INV-26） |
| 12 | **帧坐标当 client 坐标用** | **点偏 8px**（MaaEnd 实测 `(1567,1131)` vs `(1559,1130)`） | 帧是整窗 rect 的 BitBlt（含边框）⇒ 一律用 `Frame.screen_xy()`（`rect.left+cx, rect.top+cy`），**不用 `ClientToScreen`** |
| 13 | **全屏游戏期间抓帧** | 抓到的是**游戏的像素**，且能过全部不变量闸门（尺寸/非全黑/颜色数）⇒ 静默分析错画面 | 运行期**只读日志**；MaaEnd 点完开始任务后游戏全屏，抓帧仅在点击前与失败排查时做 |
| 14 | **跨运行借日志信号** | **假成功**（把上一次的 `stop_agent_impl` 当本次完成） | 日志判据必须有**时间戳基线闸**（`ZmdLogWindow`），只按字节偏移不够 |
| 15 | **把 `Frame` 当 `ndarray` 传给 `frame_changed()`；把它的 `(changed, why)` 元组当 bool** | 分支**永远走不到**（`if changed is True` 恒假）；真走到时再 `AttributeError`（`'Frame' object has no attribute 'astype'`） | `frame_changed` 吃 **`frame.rgb`**、返回 **tuple**。MaaEnd 的弱证据分支两个坑同时踩中，因日志判据总是先成功而从未暴露（`probe/zmd_click_selfcheck.py` 已覆盖） |
| 16 | **「窗口体上真实点击」不验证落点** | 点进了**别的程序**（MaaEnd 实测：鹰角启动器盖住目标 95%，固定兜底点 (999,356) 正落在启动器上）⇒ 激活交给了别的程序，框架只看到「真实点击也没用」，报 INV-8 时还误导成「等 10 秒就好」 | 兜底点击前先 `win32.raise_window()` 抬 Z 序，再**逐点**用 `top_window_at(x,y)==hwnd` 验证候选点；**一个都验不过就不点**，把遮挡者 hwnd+标题写进报错（`input._activation_candidates` / `covering_window`，`probe/activate_selfcheck.py` 覆盖） |
| 17 | **目标程序启动时自我更新 ⇒ 就绪后自行关闭** | 节点 4/5 明明都通过（窗口出现、尺寸连续稳定），**几十秒后窗口消失**；节点 6/7 报 `INV-12 GetWindowRect 失败`、`INV-8 置前台失败`——**两个报错都指向错误方向**，看起来像框架点错，实际是程序自己退了（ok-ww 实测：`is_updated=True` v3.7.3→v3.7.4，就绪后 12s `ok:quit app`） | 见「就绪后窗口消失」先**读目标程序自己的日志**（ok-ww：`data/apps/ok-ww/working/logs/ok-script.log` 的 `get_startup_version_change is_updated=True` 与 `ok:quit app`）再判责；自我更新是**一次性**的，重启一次即恢复（§FRAMEWORK 5.11 实测重跑全绿） |
| 18 | **目标程序自我更新**（MaaEnd 形态与 ok-ww 不同：更新完**自动重启并弹模态框**，要人点「知道了」） | ①下载/安装期间**进程会重启、hwnd 全换**，节点 5 在采样期只能诚实地说「窗口未就绪」，白等；②弹窗的模态遮罩把**身份锚点压暗**（「开始任务」白占比 0.171 → **0.000**）⇒ 节点 6 身份校验**必然失败**，看起来像抓错窗口 | zmd 专属两段闸门：**节点 5 只读日志等收敛**（`zmd_update_wait`，不点任何东西，放在 `require_hwnd` 之前以防旧句柄），**节点 6 双证据点「知道了」**（`zmd_update_dismiss`：应用日志 `检测到刚更新完成` **且** 帧里有 ack 绿块）——只有标记没按钮 ⇒ `no_modal` **立即返回**。⚠️应用日志每次启动清空重建（`<日期>-<n>.log`），该标记会一直留到下次启动，**「有标记」≠「此刻有弹窗」**；判更新只认包名含 `MaaEnd-win-x86_64` 的下载（资源包同走 download 模块）。见 FRAMEWORK §5.12 |

### 2.2 十二条硬性规则

1. **窗口尺寸会变**（ok-ww 实测 1200×800 / 1500×1000 / 1800×1200 / 1875×1250 / 1822×1000；ok-nte 实测 1393×1047 / 1520×1020）。**每次操作前重新读 rect，绝不缓存。**
2. **`hwnd` 每次运行都不同**（ok-ww 实测 9834000 / 198446142 / 55771756 / 651954484 / 21827074）。**不得写入配置或资产。**
3. **用标题正则发现窗口**，不可精确相等。真实标题：`OK-WW v3.6.7 China  - OK-WW`（**两个空格**）、`ok-nte v1.4.6 China  - ok-nte`。
4. **点击前必须重新判定前台**，且进一步确认**目标坐标处最顶层窗口是目标程序**。
5. **前台切换用 `SetForegroundWindow`**，**不要点任务栏**（任务栏按钮无独立 HWND，位置不稳定）。
    它常失败，且失败分两层：**抢不过来**（游戏占住前台，FAULT #35）与
    **点错人**（兜底点击落在遮挡者身上，FAULT #36）。两条的现象、根因、现场与处置
    **只在 [FAULT-LOG.md](./FAULT-LOG.md) 写一遍**；这里只留实现要点 ——
    `input.ensure_foreground` 在 10 次 API 重试**全部用尽之后**才走兜底：
    `raise_window` 抬 Z 序 → 逐个候选点 `top_window_at(x,y) == hwnd` 验证 →
    **一个都验不过就不点**，把遮挡者写进报错。
6. **匹配阈值取 0.90，不要取 0.95** —— 布局偏移会让正确页面降到 0.9402，0.95 会误拒。
7. **判断 Win32 调用成败只看返回值**，`GetLastError` 可能是无关调用的残留（实测残留值 203）。
8. **清理由 hwnd→pid 反查**；框架是**独占式**的（同时只跑其中一个）。
9. **不要依赖 `PrintWindow`** —— 对 Qt 自绘窗口返回**全黑**。只能屏幕抓图。
10. **提权环境下的 `GetCursorPos 拒绝访问` 是良性的** —— 本框架不用该 API，可无条件忽略。
11. **页面级元素必须配页面锚点**：ok-nte 的「开始」按钮**在 3 个页面出现**，仅凭按钮无法确定在哪一页。用「页面标题文字」+「按钮」两级锚点。
12. **判责之前先读目标程序自己的日志**：框架报 `INV-12 窗口已销毁` / `INV-8 置前台失败` 时，
    先确认是「程序自己退了（自我更新、崩溃、跑完）」还是「框架操作错了」。ok-ww 的自我更新
    （2026-10-19 05:20 实测）就伪装成了框架的置前台失败。

---

## 3. 单次任务流程（两条已跑通的路径）

### 3.1 ok-ww

```
1. 发现 ok-ww 窗口（标题正则）         -> hwnd, rect
2. ShowWindow(SW_RESTORE) + 校验 rect   -> 防最小化
3. SetForegroundWindow + 验证            -> GetForegroundWindow()==hwnd
4. 抓帧                                  -> BitBlt
5. 校验：帧尺寸==rect、内容非全黑、身份（侧栏在 (16,215)）
6. 导航（若不在任务页）：匹配 1_ww.png -> 点击侧栏图标
7. 定位「每日任务」行：
    锚点 = 2_ww.png[35:72]  （「每日任务」四字）
    score >= 0.90 且 **全帧唯一**
8. 同行扫描「开始」按钮：
    在行 y 带内找 >200 亮像素的列簇，取**最右**者
    交叉验证：按钮中心 y 必须落在行范围内
9. 遮挡判定 -> 点击
10. 验证生效：横幅由「已完成」变为「运行中 … 0h 0m Xs」
```

**实测坐标参考**（1822×1000 窗口）：侧栏图标窗口内 `(29,230)`；「每日任务」行 y≈570（有进度面板时）/ y≈92（无面板时）；「开始」按钮窗口内 `(1682,589)`。

⚠️ **这些坐标仅供调试对照，绝不可硬编码** —— 尺寸一变就全错。

### 3.2 ok-nte（**与 ok-ww 同一套两级锚点**）

```
1-4. 同上（标题正则含 'ok-nte'；⚠️ 须按窗口类排除第一层 Tauri Window）
5. 校验：帧尺寸==rect、内容非全黑、身份（4_nte_menu.png ☰ 可见）
6. 导航：点侧栏 index 3（任务页；ok-ww 是 index 2，二者不同）
7. 页面锚点 3_nte_daily.png -> 确认在哪一页，须唯一
8. 动作元素：action=None -> **行结构扫描**（与 ok-ww 同构，仅按钮色为青）
9. 交叉验证（按钮 y 落在行内）+ 遮挡判定 -> 点击
10. 验证生效：动作元素消失/变化（实测 1.0000 -> 0.2968）
```

**⚠️ 判定「已在任务页」必须同时满足页面锚点 + 动作元素**：
ok-nte 的「关于」页上页面锚点曾得 **0.9373**（假阳性），导致误判"已在任务页"而**跳过导航**（INV-33）。

⚠️ **ok-nte 的执行内容由复选框决定**，点击位置不决定跑什么。框架若不管理勾选，须假设用户已配置好
（用户决策：**不检查勾选状态**，由用户自行配置）。
⚠️ **ok-nte 侧栏可能无法展开**（实测点 ☰ 未展开），故不能靠侧栏文字标签定位。

---

## 4. 已知非问题（不要浪费时间）

- **`MergeEchoTask Failed找不到对话框左侧按钮`** —— ok-ww 的非致命错误，不影响完成判定。
- **`pywintypes.error: (5, 'GetCursorPos', '拒绝访问。')`** —— 良性，本框架不用该 API。
- **游戏崩溃**（`The Game has crashed and will close`）—— 游戏/环境问题，超出框架范围。经用户确认**不处理**。
- **第一层 exe 自行退出**（`ok-ww.exe` / `ok-nte.exe`）—— 正常（交接完毕），**不是崩溃**。
- **ok-nte 侧栏无法展开** —— 实测点 ☰ 无反应，属其固有设计，不是点击失败。
- **多个 `pythonw` / 多个 `msedgewebview2`** —— 正常。ok-nte 用 WebView2，会有多个子进程。
- **运行期弱证据采样的 `INV-13 本轮抓帧失败：帧几乎全黑`** —— 正常。ok-ww / ok-nte 开始跑任务后**游戏全屏**，`capture` 抓到的是游戏像素；加载/换场景期间常是纯黑（04:00 那轮 ww 的 0～152s 连续 68 次 `均值 RGB (0,0,0)`，随后恢复成 98～113 的画面指纹并照常跑完）。
  这是**不变量在正确工作**（拒答而不是分析黑帧），不是抓图坏了；只有**点击前**抓帧全黑才需要停手（见 INV-13）。

---

## 5. 模块划分

`orchestrator/` 包已按下列形态落地（不再是建议）：

```
orchestrator/
├── window.py      窗口发现（标题正则）、rect、置前台+验证、遮挡判定、hwnd→pid
├── capture.py     抓帧（BitBlt）、帧尺寸校验、内容校验（身份校验见 match）
├── match.py       模板匹配、**唯一性检查**、☰ 检测、侧栏项检测（程序专属段已进 apps/）
├── verdict.py     通用 `LogWindow`（按字节偏移 + 时间戳闸取日志窗口）与 `verdict_for` 分派
├── frameops.py    节点 8 的**程序无关**助手：`grab`/`shot`/`frame_changed`/`finish`/`CLICK_*` 阈值
├── statuses.py    叶子常量（任务终态 / 节点结果 / ok-script 共用终止标记），无 import
├── apps/          **每程序一个包**：`<key>/__init__.py`（定位 + 身份证据 + 判据）、`<key>/nodes/__init__.py`（该程序节点清单 `NODES`）、`<key>/nodes/stepN_*.py`（专属节点），见 docs/adr/0003 / 0005
├── input.py       SetCursorPos + SendInput 点击
├── assets.py      图像资产登记（读 assets.json：图像 + 比例位置 + 出生尺寸 + 用途）
├── programs.py    目标程序清单（`Program` 数据类；`ALL` 是**唯一来源**）
├── targets.py     `--target` 表达式的解析与顺序（加程序不用改这里）
├── cleanup.py     按血缘清理（见 VERDICT.md §8）
├── logretention.py 日志保留：`logs/runs/` 只留最近十轮（按**目录名时戳**排序，不看 mtime；GUI 跑完静默清理，见 RUNBOOK.md §11）
├── steps/         引擎（`main`/`context`/`chain`）+ 共用节点 `common/`（1/2/4/5/6/7/9 与节点 8 骨架 `push.py`），见 RUNBOOK.md
└── assets.json    当前加载的资产清单
```

⇒ **`window` / `capture` / `match` / `input` 四个模块的设计目标就是三个操作型程序共用**（FOS 不用它们：它不抓帧、不匹配、不点击），
新增程序时加一条 `Program` + `apps/<key>/`（含 `nodes/` 清单），而非复制代码。
反向的纪律同样重要：**专属逻辑不许写回共用文件**（ADRs 0003）—— 写回去就等于恢复
「改 A 波及 B」，且波及是静默的。

### 5.1 多目标配置形态（已落地为 `orchestrator/programs.py`）

> ✅ 已实现：`Program` 数据类 + `programs.get("ww"|"nte"|"zmd"|"fos")`，`ALL` 是唯一来源；
> 链条属于每个程序（`apps/<key>/nodes/__init__.py` 的 `NODES`，节点数/编号/顺序随程序，见 ADR 0005），
> `--target zmd|ww|nte|fos|all`（`both` 是历史别名）；**多个时按书写顺序执行**，`ALL` 只决定默认顺序。
>
> ⚠️ 两条与旧原型的实测修正：**`hwnd` 绝不进配置**（硬性规则 2）；**窗口尺寸不做常量约定**（硬性规则 1，
> 资产按 INV-39 归一化比例匹配）。字段名以 `programs.py` 为准，本文件不再抄一份。
>
> ⚠️ 时间上限是**按程序**的：`Program.run_timeout`（省略 = 主控默认 1800s；FOS = 5400s，实测 73 分钟）
> 与 `Program.wait_flag` / `wait_sid`（「等它自己退出」的节点；主控会把**剩余墙钟**灌进那个旗标）。
> 为什么必须成对：主控只在节与节之间查截止时间，睡得久的节点自己不许上限就会拖过整轮 —— FAULT #39。
>
> ⚠️ 未收敛：ok-ww 身份锚点现用 `1_ww.png`（侧栏图标），而 FRAMEWORK §4.4 推荐 **☰ 菜单图标**
> （1458×800 下 1_ww 实测仅 0.3962）。

### 5.2 尚未完成 / 建议后续

| 项 | 说明 |
| --- | --- |
| **前台卡死复现** | FRAMEWORK §2.4：窗口不在前台时 ok-ww 静默挂起、无报错。**未受控复现**，建议补 |
| **游戏 launcher 残留** | ok-nte 只关游戏本体 `HTGame.exe`，**留下 `NTEGame.exe`**（launcher，7~9 个窗口含托盘图标）。节点 9 已在 `completed` 分支报出，但按 Q3 **不主动杀**。⚠️ **清理时必须显式用跨程序入口** `watchdog.force_close(None, all_programs=True)` —— `force_close(None)` 的 `None` **不等于「全部」**，会回落到 `programs.DEFAULT`（ok-ww），只按 `Client-Win64-Shipping.exe` 查，然后报「游戏进程已全部退出」（**为真但误导**，见 FAULT #32） |
| **通用唯一性 API** | 把「全帧所有 >=0.85 位置」做成标准接口，任何定位都必须过这一关 |
| **性能** | 当前 `all_hits` 是 Python 逐点循环，1520×1020 全帧扫描很慢。正式实现应用 numpy 向量化（`stride_tricks` + 矩阵相关） |

### 5.3 节点清单与钩子参数

原先这部分写在 [CONTEXT.md](./CONTEXT.md) 的术语条目里（术语表不该做实现索引，见 [ADR 0007](./adr/0007-doc-layering-single-source.md)），搬到这里：

- **清单元素**：`Node(sid, name, label, why, has_args, shared)`。`sid` 是**该程序清单内**的编号（不连续是刻意的——三个操作型程序的链条里没有节点 3；FOS 的 3 是它自己的「等它自己退出」）；`has_args=True` 表示该节点有程序专属参数（GUI 行尾标 ★）；`shared` 区分共用节点与专属节点。
- **清单位置**：`orchestrator/apps/<key>/nodes/__init__.py` 的 `NODES` 字面量。它是「这个程序跑哪几节」的**唯一出处**：`--list`、主控（`steps/main.py`）与 GUI 都只读它。
- **共用节点**（`shared=True`）：实现固定在 `orchestrator/steps/common/<name>.py`，**不认识任何具体程序**；程序差异只能经下列钩子参数传入。

  | 节点 | 钩子参数 |
  | --- | --- |
  | 5 | `pre_ready` |
  | 6 | `pre_frame` / `identity` / `identity_hint` |
  | 8 | `push.run` 的 `navigate` / `locate` / `wait` / `before_click` / `locate_note` |

- **专属节点**（`shared=False`）：实现固定在 `orchestrator/apps/<key>/nodes/<name>.py`，只服务该程序，不得被别的程序的节点 import。
- **清单漂移的检测点**：`orchestrator/steps/chain.py` 的 `check_all()` 是引擎侧检查（清单缺失/为空、编号重复、节点文件不在、目录里有清单未登记的 `step*.py`）；GUI 启动时逐程序比对并告警。二者是同一项检查的两处实现。

---

## 6. 工作方式建议（血泪教训）

1. **每一步都验证「我操作的是不是我以为的那个东西」。** 开发期间因为没有这一步，产生了多次错误结论。
2. **写负向对照实验。** 一个从不报错的校验器等于没有校验器。已验证：故意用 1200×800 抓 1500×1000 的窗口，校验器**确实报错**。
3. **区分「证据不足」与「结论错误」。** 开发中曾把前者过度处理成后者，导致错误地撤回了正确结论。
4. **改 Markdown 用 edit/write 工具，不要用 PowerShell 文本管道** —— 会破坏 UTF-8 编码（本仓库已发生过一次，583 个字符损坏）。
5. **抓图必须落盘供肉眼复核。** 只靠数字（分数、亮度）会漏掉「抓到的是别的窗口」这类问题。
6. **新目标的适配流程**（ok-nte 用的就是这套）：
   ① 启动并勘察进程/窗口结构 → ② 抓整窗肉眼确认 → ③ 用模板试匹配 → ④ **逐页扫描**找模板在哪页 → ⑤ **验证唯一性** → ⑥ 必要时新采锚点 → ⑦ 端到端 dry-run → ⑧ 实跑。
7. **Tk 窗口在远程会话下收不到合成点击 —— 别再用点击复核 GUI。**
   实测（2026-10-16，GameViewer 在运行）：`desktop_click` 报告「落点与目标一致」
   （光标读数也确实到了目标像素），但 `ttk.Button` 与 `ttk.Combobox` **毫无反应** ——
   下拉框不展开、点「运行编排」日志仍空白、按钮不变灰。
   `desktop_diagnose` 却报「落点稳定，鼠标点击可用」，**这个诊断不足以证明点击有效**。
   ⇒ 复核 GUI 行为要走**程序化路径**：
   - 界面逻辑：用 Tk 自己的 API 直接调回调（见 `probe/_probe_gui_target_wire.py`）；
   - 视觉：`desktop_capture` **抓图**仍然有效（抓图与输入是两条通道），
     配合 `probe/_probe_gui2_visual.py` 等自检。

8. **长跑子进程的 stdout 不要挂到「没人读的 PIPE」上（FAULT #36，2026-10-18 实测）。**
   `subprocess.PIPE` 且父进程不读 ⇒ 管道缓冲（64 KiB）写满后，子进程**连同它自己
   `subprocess.run` 拉起的孙进程**一起阻塞在 write 上，整轮**静默挂死**：不抛异常、
   无退出码、输出文件恒 0 字节，表面看像「编排卡在节点 5」。
   诊断特征（这次逐条对上）：进程存活但 **CPU 仅 0.0x 秒**、**RSS 只有 ~19 MB**
   （连 numpy 都没 import）、线程 `WaitReason=Executive`、父子两进程栈顶同为 `write`。
   ⇒ 长跑一律 `stdout=open(输出文件, "w")`，或起 reader 线程把管道抽干。
9. **Windows 上「原子替换」与「有别的进程在读」是互斥的（FAULT #37，2026-10-18 实测）。**
   `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` 遇到目标文件正被打开（**只读打开也算**）
   就返回 `ERROR_ACCESS_DENIED`(5) —— CPython 的 `open()` 只共享 READ|WRITE，
   **不共享 DELETE**。表现为节点里 `os.replace('...state.json.tmp','...state.json')`
   抛 `PermissionError: [WinError 5] 拒绝访问`，整节点 FAILED。
   撞车对象就是 **GUI 每 120 ms 读一次 `state.json`** 的那个轮询；实测撞车率
   **6.9%~7.8%**（`probe/_probe_state_race.py`：8840 次替换失败 613 次，同一夹具换成
   重试实现后 **0/8060**）。
   ⇒ **凡是「写 tmp + `os.replace`」的目标文件可能被别的进程读，就必须重试**
   （读侧单次持锁约 10 ms；本仓库用 12 次退避，合计 >0.6 s）。
10. **ttk 在 vista 主题下把「disabled + 已勾」的 Checkbutton 画成空白灰方框**
    （2026-10-18 截图实测）。也就是说：**置灰一个勾着的选项，看起来跟没勾一模一样**。
    这不像报错、也不像崩溃，只让人以为「我明明勾了怎么没生效」。
    ⇒ 要表达「这个开关暂时不生效」，**别用 `state="disabled"`**，改成
    「控件保持可用 + 旁边写明当前语义 + 用户一动它就自动切过去」
    （本仓库的做法：跟随中勾任意目标 = 自动关掉跟随）。

---

## 7. 关键产物索引

| 文件 | 用途 |
| --- | --- |
| `probe/capture.py` | 窗口发现、抓帧、帧统计、PNG 落盘 |
| `probe/template_probe.py` | `match_template`（归一化互相关）、`capture_okww` |
| **`orchestrator/targets.py`** | **目标程序清单与 `--target` 解析的唯一入口**（`parse` / `keys` / `displays` / `describe` / `validate_choices_flag` / `self_check`）。清单本身来自 `programs.ALL`；`python -m orchestrator.targets --self-check` 是它的自检 |
| **`gui/targets.py`** | **GUI 侧的目标清单**：用 `ast` 静态读 `programs.py`（不 import），读不出回落 `FALLBACK` 并告警 —— 让 GUI 在节点/主控代码坏掉时仍能打开 |
| **`probe/_probe_gui_target_wire.py`** | **GUI 目标选择器接线验证**（调真实 `on_run`，stub `Runner` 看 argv；含空选拒绝、`all`/`none` 状态机） |
| **`probe/_probe_gui_both_live.py`** | **GUI 端到端：用真实 App 驱动多目标串联**。建真的 `App`、把目标清单**全选**（得到 `--target ww,nte`）、调**真实的 `App.on_run()`**、自己抽 Tk 事件循环（`--dry-run` 2.5s 冒烟；不带参数真跑约 12 分钟）。核对项含「两轮各有一套 all-ok 的节点状态」，**取自 `state.json`** 而非 bus 推送 —— 短跑会在 `after` 轮询启动前就结束，只看 bus 会误判成 0 组 ok；另核对「每个目标行尾的进度点都不是空心」 |
| **`probe/_probe_ww_sessions.py`** | **把 ok-ww 日志按会话切开列结局**。会话边界用 `ok:ok-script init`，**不能按 `ok:quit app`** —— 异常退出的会话根本不写后者。用来找「没跑完」的真实样本 |
| **`probe/_probe_ww_unknown_cleanup.py`** | **ok-ww UNKNOWN + 游戏残留 自动收尾回归**（三层：真实历史会话判据 / 分支静态检查 / `--live` 真起游戏端到端） |
| **`probe/_probe_unknown_cleanup.py`** | **ok-nte 侧同一路径的回归**（纯静态 + 只读，随时可跑） |
| **`probe/_probe_force_close_all.py`** | **跨程序清理** `force_close(all_programs=True)` 回归（FAULT #32：`None` 不等于「全部」） |
| **`probe/_probe_foreground.py`** | **抢前台**静态 12 项 + live 实测（FAULT #29：裸调 `SetForegroundWindow` 被前台锁挡住会永久失败） |
| **`probe/_probe_foreground_click.py`** | **抢前台的最后一手**回归（FAULT #35：游戏窗口占前台时 API 全败，必须真实点击窗口体）。静态 AST 接线 + 打桩语义 + 只读几何，**不依赖 live 复现**（该病态状态偶发、事后无法按需重建） |
| **`probe/_probe_executor_pause.py`** | **执行器暂停**诊断（FAULT #30：`pos_invalid: (-32000, -32000)` 哨兵坐标）。含 `ok-script.2026-10-12.log` 作**负向**用例 |
| **`probe/_probe_stalled_live.py`** | **FAULT #30 的 STALLED 分支——真实卡死驱动**。**2026-10-18 已跑通（闭环）**：等业务行 → `ShowWindow(SW_MINIMIZE)` 返回 True → 哨兵 `og.executor.pause pos_invalid:(-32000,-32000)` → 节点 8 用时 135.8s 判 `failed` / `data.result='stalled'` → `state.result='stalled'`、主控退出码 3，即「STALLED 映射 failed 而非 timeout」成立。证据 `logs/runs/stalled-live-20261018-061325`。⚠️ 用法上踩过 FAULT #36（见 §10 第 8 条）：主控 stdout 必须落**文件**，不能挂**不读的 PIPE** |
| **`probe/_probe_state_race.py`** | **`state.json` 原子替换 vs 读轮询的撞车率**（FAULT #37：Windows 下目标文件被读打开时 `os.replace` 报 WinError 5）。两种跑法：裸 `os.replace` 测率（实测 **7.8%**）、`--verify-fix` 走**真实 `RunState.save()`**（带 `--raw` 作负向对照，应如实复现；不带则必须 0 失败） |
| **`probe/README.md`** | **`probe/` 下全部脚本的一行索引**（79 个，按门禁 / 回归自检 / 每程序 / GUI / 通用分组，含跑法与命名约定）。新增探针先看它的「新增探针的规矩」 |
| **`probe/_check_workspace.py`** | **工作区门禁**（exit≠0 = 违约），8 条判据：C1~C4 目录契约（根目录只放三份文件、`docs/` 只放文档、README 目录表对得上、无残留产物，见 ADR 0006）+ C5~C7 文档一致性（相对链接有效、「共 N 条」声明与现实一致、`INV-nn` / `FAULT #nn` / `硬性规则 n` 引用可解析，见 ADR 0007）+ C8 日志保留（`logs/runs/` 超过十轮只**提示**不拦，见 RUNBOOK §11）。已列入 `docs/adr/0003` 共用层回归清单第 8 条 |
| **`legacy/probe-investigation/run_daily2.py`** | **ok-ww 端到端参考实现**（九道校验） |
| **`legacy/probe-investigation/nte_run.py`** | **ok-nte 端到端参考实现**（两级锚点，八道校验） |
| **`probe/nte_main.py`** | `all_hits` **唯一性检查工具**（被多个脚本复用） |
| `legacy/probe-investigation/nte_sweep.py` | **逐页扫描**：查找模板在哪一页（通用手段） |
| `legacy/probe-investigation/nte_anchor.py` | 采集页面文字锚点 + 唯一性验证 |
| `legacy/probe-investigation/check_anchor_collision.py` / `anchor_ambiguity.py` | 锚点歧义诊断 |
| `legacy/probe-investigation/verify_negative.py` | 负向对照实验 |
| `legacy/probe-investigation/observe_v2.py` | 带身份校验的观测循环 |
| `legacy/probe-investigation/watch_autoclose.py` / `nte_watch.py` | 自动关闭 / 状态观测 |

> ⚠️ **表中带 `legacy/probe-investigation/` 前缀的是开发期一次性调查工具**，已移入 `legacy/`
> （原始用途清单见各脚本头部 docstring）。保留作**证据追溯**，
> 不参与生产流程。核心模块（`capture.py`、`template_probe.py`、`nte_main.py`）仍在 `probe/`。

