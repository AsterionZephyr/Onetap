# 实现交接书：ok-ww / ok-nte 黑盒编排

> **读者：接手的 agent。** 你不需要重读全部探测脚本，但**必须**读完本文的「必须遵守的约束」。
> 详细依据见 [FRAMEWORK.md](./FRAMEWORK.md)（不变量 + 各阶段实测记录 + §0.1 目标程序差异一览）。
> 术语以 [CONTEXT.md](./CONTEXT.md) 为准。

---

## 0. 一句话目标

在**进程外**、以**真实光标**、**黑盒**地操作 ok-ww 与 ok-nte：
启动 → 导航到任务页 → 点「开始」→ 等待任务完成 → 确认程序自行退出。

**两个程序均已验证可行**（ok-ww：FRAMEWORK §5.8；ok-nte：FRAMEWORK §0.1 与编排实测）。
**最终目标是按顺序启动这些程序完成任务。**

### 0.1 三个目标程序（ww/nte 结构同构，MaaEnd 结构不同）

| | ok-ww | ok-nte | **MaaEnd（zmd）** |
| --- | --- | --- | --- |
| 层数 | 两层 | 两层 | **单层**（`MaaEnd.exe` 自己持窗口） |
| 第一层 | `ok-ww.exe`（Tauri Window, `ok-ww`） | `ok-nte.exe`（Tauri Window, `ok-nte`） | —— |
| 第二层（窗口持有者） | `pythonw` + `Qt6111QWindowIcon` | `pythonw` + `Qt6112QWindowIcon` | `MaaEnd.exe` + **`Tauri Window`（精确相等）** |
| 标题 | `OK-WW v3.7.3 China  - OK-WW` | `ok-nte v1.4.8 China  - ok-nte` | `MaaEnd v2.34.0-beta.1` |
| 子窗口 | **0** | **0** | **0** |
| 界面 | 多页 + 侧栏，**需导航** | 多页 + 侧栏，**需导航** | **单页**，无导航 |
| 任务页（侧栏 index / y） | index **2** / ≈**230** | index **3** / ≈**329** | —— |
| 身份锚点 | `3_ww_menu.png`（☰） | `4_nte_menu.png`（☰） | **底部绿色「开始任务」按钮**（色块取证） |
| 页面锚点 | `2_ww_page.png` | `3_nte_daily.png` | ——（单页） |
| **执行模型** | **每行一个「开始」** | **每行一个「开始」**（v1.4.8 起） | **一个「开始任务」提交整条队列**（实测 12 个 task_id） |
| 动作元素定位 | 行扫描（按钮**白**） | 行扫描（按钮**青**） | **色块范式**（绿 `#008B45`）+ 底部带 + 多重闸门 |
| 终态判据 | `ww_verdict`（阶段序列） | `nte_verdict`（终止标记） | `zmd_verdict`（`mxu-tauri.log` 的 `stop_agent_impl` + **时间戳闸**） |
| 目标游戏 | `Client-Win64-Shipping.exe` | `HTGame.exe` | `Endfield.exe`（`UnityWndClass`） |
| 日志 | `ok-ww\data\apps\ok-ww\working\logs\` | `ok-nte\data\apps\ok-nte\working\logs\` | `zmd\debug\mxu-tauri.log`（**另两个每次启动被清空**） |
| 正常完成 | 自行退出 | 自行退出 | **不立即退出**（实测完成后 29 分钟仍存活，见 §6.4） |
| 可执行文件 | `E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe` | `E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe` | `E:\TOOLS\ScriptsGames\zmd\MaaEnd.exe` |

**操作机制完全一致**，差异只在进程/窗口标识、界面布局与判据模块。⇒ **框架代码按程序配置驱动，不复制三份。**
配置入口是 `orchestrator/programs.py` 的 `ALL`（唯一来源），节点 8 只有专属交互分支（ww 定位链 / nte / zmd）。

> ⚠️ **ok-nte v1.4.8 改版**：早期是「单行日常任务 + 右下角唯一一个开始按钮」，
> 现已改为**逐任务行**（每行一个「开始」，实测 **9 个同款按钮**）。
> ⇒ 旧方案「两级锚点用固定按钮模板 `2_nte.png`」**已作废**（`assets.json` 标其为已弃用），
> 与 ok-ww 一样改走**行结构扫描**。差异一览见 FRAMEWORK §0.1。

---

## 1. 环境（实测确定，不要改）

| 项 | 值 |
| --- | --- |
| Python | **`D:\WORKs\Anaconda\python.exe`**（3.13.9） |
| 可用库 | **Pillow 12.0.0、numpy 2.3.5、win32gui、win32api** |
| **不可用** | cv2、pyautogui、mss（**未安装，不要引入**） |
| 系统 Python | `C:\Python314` —— **四个库全无，不可用** |
| ok-ww 可执行 | `E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe` |
| ok-nte 可执行 | `E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe` |
| 本机屏幕 | 2560×1440 物理 |
| **必须提权运行** | 两个程序都是 `requireAdministrator`；非提权会话连杀进程都会被拒 |
| 远程软件 | GameViewer 在运行（会改缩放；**不要依赖固定分辨率**） |

**抓图**：`ctypes` + `BitBlt`（见 `probe/capture.py`）。
**匹配**：numpy 归一化互相关（见 `probe/template_probe.py` 的 `match_template`）。
**输入**：`SetCursorPos` + `SendInput`（参考实现见 `legacy/probe-investigation/run_daily2.py`）。

---

## 2. 必须遵守的约束（每条都有实测依据，违反即产生静默错误）

### 2.1 会静默出错的地方（最重要）

这些失效**不抛异常、不返回错误码**，只给错误结果。**必须主动校验**。（第 12~16 条由 MaaEnd 接入暴露。）

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
| 16 | **「窗口体上真实点击」不验证落点** | 点进了**别的程序**（MaaEnd 实测：鹰角启动器盖住目标 95%，固定兜底点 (999,356) 正落在启动器上）⇒ 激活交给了别的程序，框架只看到「真实点击也没用」，报 INV-8 时还误导成「等 10 秒就好」 | 兜底点击前先 `win32.raise_window()` 抬 Z 序，再**逐点**用 `top_window_at(x,y)==hwnd` 验证候选点；**一个都验不过就不点**，把遮挡者 hwnd+标题写进报错（`input._activation_candidates` / `covering_window`，`probe/activate_selfcheck.py` 覆盖） |
| 15 | **把 `Frame` 当 `ndarray` 传给 `frame_changed()`；把它的 `(changed, why)` 元组当 bool** | 分支**永远走不到**（`if changed is True` 恒假）；真走到时再 `AttributeError`（`'Frame' object has no attribute 'astype'`） | `frame_changed` 吃 **`frame.rgb`**、返回 **tuple**。MaaEnd 的弱证据分支两个坑同时踩中，因日志判据总是先成功而从未暴露（`probe/zmd_click_selfcheck.py` 已覆盖） |

### 2.2 十三条硬性规则

1. **窗口尺寸会变**（ok-ww 实测 1200×800 / 1500×1000 / 1800×1200 / 1875×1250 / 1822×1000；ok-nte 实测 1393×1047 / 1520×1020）。**每次操作前重新读 rect，绝不缓存。**
2. **`hwnd` 每次运行都不同**（ok-ww 实测 9834000 / 198446142 / 55771756 / 651954484 / 21827074）。**不得写入配置或资产。**
3. **用标题正则发现窗口**，不可精确相等。真实标题：`OK-WW v3.6.7 China  - OK-WW`（**两个空格**）、`ok-nte v1.4.6 China  - ok-nte`。
4. **点击前必须重新判定前台**，且进一步确认**目标坐标处最顶层窗口是目标程序**。
5. **前台切换用 `SetForegroundWindow`**，**不要点任务栏**（任务栏按钮无独立 HWND，位置不稳定）。
    ⚠️ **FAULT #35（实测 2026-10-17）**：**游戏窗口占住前台时，API 抢不过来** ——
    `set_foreground` 三手段（裸调 / `AttachThreadInput` / ALT 抖动）对它 **10/10 全败**，
    且**最小化游戏也不释放**前台。此时唯一有效的是**在目标窗口体上真实点击一次**
    （点 `top + min(18, h//8)`、`left + max(20, w//5)`，即标题栏偏左，避开右上角按钮与主体控件）。
    实测点击一次即夺回，随后 `ensure_foreground` 立即通过（3/3）。
    `input.ensure_foreground` 现已实现这一手（`_click_to_activate`），在 10 次 API 重试
    **全部用尽之后**调用一次 —— 也是这条规则里「真实点击能拿到激活」那半句的兑现。
    ⚠️ **FAULT #36（实测 2026-10-19 03:20）**：兜底点击**必须先验证落点**。MaaEnd 跑完
    它自己拉起的启动器后，鹰角启动器（`Qt5158QWindowIcon`，1312×754 @ (624,323)）抢在前台、
    盖住 MaaEnd 95% 且**线程不响应** ⇒ `SetForegroundWindow` 永久失败；固定兜底点落在启动器上，
    点击把激活交给了**别的程序**。现为「抬 Z 序 → 逐点 `top_window_at` 验证 → 验不过不点」。
6. **匹配阈值取 0.90，不要取 0.95** —— 布局偏移会让正确页面降到 0.9402，0.95 会误拒。
7. **判断 Win32 调用成败只看返回值**，`GetLastError` 可能是无关调用的残留（实测残留值 203）。
8. **清理由 hwnd→pid 反查**；框架是**独占式**的（同时只跑其中一个）。
9. **不要依赖 `PrintWindow`** —— 对 Qt 自绘窗口返回**全黑**。只能屏幕抓图。
10. **提权环境下的 `GetCursorPos 拒绝访问` 是良性的** —— 本框架不用该 API，可无条件忽略。
11. **页面级元素必须配页面锚点**：ok-nte 的「开始」按钮**在 3 个页面出现**，仅凭按钮无法确定在哪一页。用「页面标题文字」+「按钮」两级锚点。

---

## 3. 程序链条（九个节点）

| # | 节点 | 要点 |
| --- | --- | --- |
| 1 | **提权检查** | 非管理员直接中止 |
| 2 | **启动 `ok-ww.exe`** | |
| 3 | **等待第二层**（原「跨过第一层」） | **不点也会自动放行，约 21 秒**。人工点击只是**加速**，不是必经关卡 |
| 4 | **确认窗口持有者** | 找 `pythonw`，反查 hwnd；`ok-ww.exe` 稍后会自行退出 |
| 5 | **等待窗口就绪** | 标题正则匹配 + rect 连续采样稳定 |
| 6 | **抓首帧校验** | INV-1 尺寸 + 内容非全黑 |
| 7 | **置前台 + 遮挡判定** | 见 2.2 第 4 条 |
| 8 | **任务循环** | 见 §4 |
| 9 | **退出与清理** | 任务完成后 ok-ww **会自行退出**，框架只需确认 |

**节点 3 的实测时间线**（全程零点击）：`pythonw` 21.5s 出现 → Qt 窗口 25.2s 出现 → `ok-ww.exe` 约 27s 消失。

---

## 4. 单次任务流程（两条已跑通的路径）

### 4.1 ok-ww

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

### 4.2 ok-nte（**与 ok-ww 同一套两级锚点**）

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

## 5. 图像库规格

### ok-ww

| 资产 | 尺寸 | 用法 |
| --- | --- | --- |
| `templates/3_ww_menu.png` | 21×18 | **身份锚点**（☰）。页面无关、唯一。主用程序化检测，此为回退 |
| `templates/2_ww_page.png` | 330×38 | **页面锚点**（日历图标 + 「每日任务」）。✅ 1.0000 且唯一 |
| `templates/2_ww.png` | 1823×42 | 整行。**不可整行匹配**，仅供行结构理解 |
| `templates/1_ww.png` | 27×31 | 侧栏图标。**已不用于身份**（小尺寸下仅 0.3962） |

### ok-nte

| 资产 | 尺寸 | 用法 |
| --- | --- | --- |
| `templates/4_nte_menu.png` | 26×20 | **身份锚点**（☰）。页面无关、唯一。主用程序化检测，此为回退 |
| `templates/3_nte_daily.png` | 155×35 | **页面锚点**（首行任务名）。✅ 唯一 |
| `templates/2_nte.png` | 103×46 | ~~动作元素~~ ❌ **已弃用**（v1.4.8 改行扫描，9 个同款按钮必然歧义） |

**元数据以 [`templates/assets.json`](./templates/assets.json) 为准**（含 `owner` / `app_version` / 用途）。
**资产必须记录**：图像、**点击位置（比例 `relative_x`/`relative_y`）**、**出生尺寸**、`app_version`。

**`2_ww.png` 结构分解**（v3.6.7 时代；v3.7.3 起页面锚点已独立为 `2_ww_page.png`）：

| 区段 | x | 用途 |
| --- | --- | --- |
| 日历图标 | 9..25 | ❌ **禁用**（进度面板有同款，实测 2 个候选） |
| **「每日任务」** | **35..72** | ✅ **唯一锚点**（v3.6.7）；v3.7.3 需含图标，见 INV-35 |
| 描述文字 | 116..451 | 辅助校验 |
| 空背景 | 452..1215 | ❌ **无鉴别力** |
| 「▶ 开始」 | 1216..1313 | 点击目标（位置须按行结构重算） |

---

## 6. 状态判定（框架必须自己做，不能指望程序）

### 6.1 ok-ww：两种完全不同的终止行为

| 情形 | 行为 | 判定依据 |
| --- | --- | --- |
| **正常完成** | **自行退出** | 通知「成功执行任务, 正在退出游戏和App!」+ `pythonw` 消失 |
| **卡在等待条件** | **永不超时，无限等待** | 计时器**冻结**（实测冻结在 1m32s）、错误栏显示原因 |

**因此框架必须**：
- 自行判定「完成 / 失败 / 超时」，并具备**中止能力**；
- 区分上述两种终止 —— **不能把「进程还在」当作「还在正常跑」**；
- 读**进度面板**：横幅文案（`运行中`/`已完成`）、`current task`、`日志`、`错误`。

**实测的等待态错误示例**：`请在大世界并在队伍中开始！` —— 此时任务完全停顿。

### 6.2 ok-nte：页面锚点 + 动作元素

| 状态 | 判定方法 |
| --- | --- |
| **空闲** | 页面锚点命中 **且** 行扫描仍找到「开始」按钮 |
| **运行中** | 动作元素消失/变化（实测动作元素 score **1.0000 → 0.2968**） |

⇒ **注意**：v1.4.8 起动作元素由**行扫描**得出（每行一个按钮），
**不再**是「一个固定按钮模板的匹配分数」（`2_nte.png` 已弃用）。

**⚠️ ⚠️ 但「空闲」不能作为完成判据** —— 见 §6.3。

### 6.3 ⚠️ 空闲态 ≠ 完成（**实测踩过的坑**）

**「`▶ 开始` 重新出现」有两种原因，无法由按钮形态区分**：

| 原因 | 含义 |
| --- | --- |
| 任务全部成功完成 | ✅ 真正完成 |
| **任务失败/中断** | ❌ 回落 |

**实测教训**：ok-nte 回到空闲态，开发时据此刻判为"完成"，**实际是任务失败**。
（用户指出：ok-nte **正常完成后同样会自动退出**，那次未退出正因失败。）

⇒ **两程序正常完成都会自行退出。** 但**终态判定必须另有成功判据**：

| 手段 | 说明 |
| --- | --- |
| **完成提示** | ok-ww 有「每日任务已完成」+「成功执行任务, 正在退出游戏和App!」 |
| **交叉印证** | 退出**且**有完成提示 → 成功；退出**但无**提示 → 判断为异常 |
| **程序日志** | ok-nte：`E:\TOOLS\ScriptsGames\ok-nte\logs\` |

⇒ **INV-30：证据不足时报「未知/失败」，绝不默认「成功」。**
⇒ 注：上表「两程序」指 ok-ww / ok-nte。**MaaEnd 不自行退出**，见 §6.4。

### 6.4 MaaEnd：完成 ≠ 进程退出（**判据只看日志**）

**MaaEnd 跑完后 `MaaEnd.exe` 不会立刻退出**（与 ww/nte 相反：那两个完成即自行退出）。
实测 22:26:37 完成 → 22:55:59 仍在 → 22:56:14 才出现 `[telemetry] 已结束 Session`，
**退出原因日志未记录**（没有 exit 命令行），无法判定是人工关闭还是自身退出。
⇒ 「进程消失」在它身上既非成功标志也非失败标志 —— 唯一的明确完成信号在日志里：

```
[2026-10-18][22:26:37][INFO][mxu_lib::commands::maa_agent] stop_agent_impl called for instance: yj2gs5w
```

| 信号 | 位置 | 用途 |
| --- | --- | --- |
| `stop_agent_impl called for instance: <id>` | `zmd\debug\mxu-tauri.log` | **主判据**（唯一明确终止信号） |
| `[start_tasks] All tasks submitted, total: N task_ids` | 同上 | 点击生效的确认（节点 8d） |
| `[MXU_KILLPROC] Killing process: <game>` | 同上 | 辅助完成证据（「关游戏」内置任务，实测排最后一条），**须注明** |
| `run_pretask finished with exit code: 1` | 同上 | **启动失败**（多半是启动器路径没配好） |

**两个必须知道的坑**：

1. **`mxu-tauri.log` 跨启动追加，另两个日志每次启动被清空** ⇒ 判据只认它，且必须带
   **时间戳基线闸**（`ZmdLogWindow.mark()` 记最后一行时间戳，`poll()` 丢弃更早的行）。
   只按字节偏移会在「日志被清后整段重读」时借到**上一次运行**的 `stop_agent_impl` ⇒ 假成功。
2. **两条判据只差 1 秒**（实测 22:26:36 关游戏 → 22:26:37 stop_agent）。代码在关游戏后**继续在收尾宽限里
   poll**：拿到主判据就用主判据，拿不到才退回辅助证据并**如实写明**「宽限期内未看到 stop_agent 标记」——
   否则 `state.json` 会让事后读日志的人以为该信号从未出现。

**运行期不抓帧**：点完「开始任务」后 MaaEnd 拉起启动器与**全屏**游戏，MaaEnd 被盖住 ⇒ 抓帧拿到的是
**游戏的像素**，而且尺寸=rect、非全黑、颜色数够，**所有不变量都会通过** ⇒ 典型的静默分析错画面。
⇒ 等待阶段只读日志。

---

## 7. 已知非问题（不要浪费时间）

- **`MergeEchoTask Failed找不到对话框左侧按钮`** —— ok-ww 的非致命错误，不影响完成判定。
- **`pywintypes.error: (5, 'GetCursorPos', '拒绝访问。')`** —— 良性，本框架不用该 API。
- **游戏崩溃**（`The Game has crashed and will close`）—— 游戏/环境问题，超出框架范围。经用户确认**不处理**。
- **第一层 exe 自行退出**（`ok-ww.exe` / `ok-nte.exe`）—— 正常（交接完毕），**不是崩溃**。
- **ok-nte 侧栏无法展开** —— 实测点 ☰ 无反应，属其固有设计，不是点击失败。
- **多个 `pythonw` / 多个 `msedgewebview2`** —— 正常。ok-nte 用 WebView2，会有多个子进程。

---

## 8. 模块划分（**现状已实现，见括号**）

`orchestrator/` 包已按下列形态落地（不再是建议）：

```
orchestrator/
├── window.py      窗口发现（标题正则）、rect、置前台+验证、遮挡判定、hwnd→pid
├── capture.py     抓帧（BitBlt）、帧尺寸校验、内容校验（身份校验见 match）
├── match.py       模板匹配、**唯一性检查**、☰ 检测、侧栏项检测（程序专属段已进 apps/）
├── verdict.py     通用 `LogWindow`（按字节偏移 + 时间戳闸取日志窗口）与 `verdict_for` 分派
├── frameops.py    节点 8 的**程序无关**助手：`grab`/`shot`/`frame_changed`/`finish`/`CLICK_*` 阈值
├── statuses.py    叶子常量（任务终态 / 节点结果 / ok-script 共用终止标记），无 import
├── apps/          **每程序专项模块**：`ww.py` / `nte.py` / `zmd.py`（定位 + 身份证据 + 判据 + 节点 8），见 docs/adr/0003
├── input.py       SetCursorPos + SendInput 点击
├── assets.py      图像资产登记（读 assets.json：图像 + 比例位置 + 出生尺寸 + 用途）
├── programs.py    目标程序清单（`Program` 数据类；`ALL` 是**唯一来源**）
├── targets.py     `--target` 表达式的解析与顺序（加程序不用改这里）
├── cleanup.py     按血缘清理（见 CLEANUP.md）
├── steps/         程序链条编排（九节点，见 §9）
└── assets.json    当前加载的资产清单
```

⇒ **`window` / `capture` / `match` / `input` 四个模块的设计目标就是三程序共用**，
新增程序时加配置层 + 一个 `apps/<key>.py`，而非复制代码。
反向的纪律同样重要：**专属逻辑不许写回共用文件**（ADRs 0003）—— 写回去就等于恢复
「改 A 波及 B」，且波及是静默的。

### 8.1 多目标配置形态（**已落地为 `orchestrator/programs.py`**）

> ✅ **状态更新（2026-10-16）**：本节描述的形态**已经实现**，落点是
> [`orchestrator/programs.py`](./orchestrator/programs.py)（`Program` 数据类 +
> `programs.get("ww"|"nte"|"zmd")`）。九节点链已**参数化**，三程序共用同一套节点代码，
> 通过 `--target ww|nte|zmd|all` 选择（`both` 是历史别名，见 §9）。
>
> ⚠️ 与旧原型的两处**实测修正**：
> - **`hwnd` 绝不进配置**（硬性规则 2）—— 每轮重新按标题正则发现。
> - **窗口尺寸不做常量约定**（硬性规则 1）—— 实测 1200×800 至 1875×1250 都有，
>   每次操作前重读 rect，资产按 INV-39 归一化比例匹配。
>
> 下面保留原设计原型的字段说明，供理解形态用；**字段名以 `programs.py` 为准**。

```python
TARGETS = {
    "ok-ww": {
        "exe": r"E:\TOOLS\ScriptsGames\ok-ww\ok-ww.exe",
        "title_regex": r"OK-WW",
        "window_size": (1823, 1000),        # 资产采集尺寸（INV-39 归一化）
        "nav_sidebar_index": 2,             # 按**内容簇序号**，不用绝对 y
        "nav_sidebar_y": 230,               # 仅作回退/参考
        "anchors": {
            "identity": "1_ww.png",         # 身份校验（⚠️ 见下）
            "page":     "2_ww.png[9:72]",   # 页面锚点（日历 + 「每日任务」）
            "action":   None,               # 按钮由**行结构扫描**得出
        },
        "action_scan": "find_ww_action",    # 按钮白
        "verdict_module": "ww_verdict",     # 阶段序列
        "done_when": "process_gone",
    },
    "ok-nte": {
        "exe": r"E:\TOOLS\ScriptsGames\ok-nte\ok-nte.exe",
        "title_regex": r"ok-nte",
        "window_size": (1875, 1250),        # 资产采集尺寸（v1.4.8）
        "nav_sidebar_index": 3,
        "nav_sidebar_y": 329,
        "anchors": {
            "identity": "4_nte_menu.png",   # ☰
            "page":     "3_nte_daily.png",
            "action":   None,               # v1.4.8 起同 ok-ww，行结构扫描
        },
        "action_scan": "find_nte_action",   # 按钮青
        "verdict_module": "nte_verdict",    # 终止标记
        "done_when": "process_gone",
    },
}
ORDER = ["ok-ww", "ok-nte"]                 # 编排顺序（用户指定：ok-ww 先）
```

**差异全部落在配置里**，`window` / `capture` / `match` / `input` 四个模块**三程序共用**。

⚠️ **身份锚点两程序不同，且 ok-ww 侧有分歧**：
`orchestrator/assets.json` 当前用 `1_ww.png`（侧栏图标，位置恒为 (16,215)），
而 FRAMEWORK §4.4 推荐的策略是 **☰ 菜单图标**（页面无关，避免侧栏图标在小尺寸下失配 —— 1458×800 下实测仅 **0.3962**）。
接入时**以 §4.4 的 ☰ 为准**，或先复核 `1_ww.png` 在小尺寸下的表现。

### 8.2 尚未完成 / 建议后续

| 项 | 说明 |
| --- | --- |
| **前台卡死复现** | FRAMEWORK §2.4：窗口不在前台时 ok-ww 静默挂起、无报错。**未受控复现**，建议补 |
| ~~ok-nte 自动退出~~ | ✅ **已确证**：正常完成后自行退出（同 ok-ww） |
| ~~ok-nte 完成判定~~ | ✅ **已解决**：`nte_verdict` 用终止标记，不用按钮形态 |
| ~~勾选状态管理~~ | ✅ **已决策**：**不需要检查**，由用户自行配置 |
| ~~多程序串联~~ | ✅ **已实现**：`--target ww,nte`（按书写顺序各跑一轮；`all`/`both` 是全部的历史别名），见 §9 |
| ~~ok-nte 收尾抢跑~~ | ✅ **已修**（FAULT #27）：见完成标记后给有界 settle 窗口，等它自己关游戏 |
| **游戏 launcher 残留** | ok-nte 只关游戏本体 `HTGame.exe`，**留下 `NTEGame.exe`**（launcher，7~9 个窗口含托盘图标）。节点 9 已在 `completed` 分支报出，但按 Q3 **不主动杀**。⚠️ **清理时必须显式用跨程序入口** `watchdog.force_close(None, all_programs=True)` —— `force_close(None)` 的 `None` **不等于「全部」**，会回落到 `programs.DEFAULT`（ok-ww），只按 `Client-Win64-Shipping.exe` 查，然后报「游戏进程已全部退出」（**为真但误导**，见 FAULT #32） |
| ~~「今日任务已完成」残留需人工收尾~~ | ✅ **已自动收尾**（2026-10-16）：用户裁定「遇到『每日任务已做完导致 ok-ww 失败且进程/游戏不退出』时**自行手动关闭，不询问用户**」。节点 9 的 `unknown` 分支原先只看 `window.running(prog)`（**目标程序自己**），而该情形里 ok-ww 进程**恰恰是已经退出的那一个**，留下的是**游戏** ⇒ 旧代码打印「无残留，无需清理」**而游戏仍在跑**。现改为**两者都查**，有游戏残留就走 `watchdog.force_close`。⚠️ 注意**不能只靠 `run_cleanup`**：它按 `process_prefix` 只杀目标程序目录下的进程，游戏根本不在那里。**已两程序各自端到端验证**：ok-nte 用 `NTEGame.exe`、ok-ww 用 `Client-Win64-Shipping.exe`，探针见 §11 |
| **通用唯一性 API** | 把「全帧所有 >=0.85 位置」做成标准接口，任何定位都必须过这一关 |
| **性能** | 当前 `all_hits` 是 Python 逐点循环，1520×1020 全帧扫描很慢。正式实现应用 numpy 向量化（`stride_tricks` + 矩阵相关） |

---

## 9. 编排层设计要点（最终目标：按顺序启动多程序）

**用户目标**：按顺序启动这些程序完成任务。

**设计时必须考虑**（均有实测依据）：

1. **独占性**：同一时间只跑一个（INV-15）。编排是**串行**的，不是并发。
2. **每个程序有三种终止**，编排必须区分：
   - 正常完成（自行退出）→ 继续下一个；
   - 卡在等待条件（**永不退出**）→ 必须有**超时**，否则整个编排死锁；
   - 崩溃/异常退出 → 记录并决定是否继续。
3. **状态判定方式因程序而异**：ok-ww 读进度面板文字；ok-nte 看按钮形态。**编排层不应理解这些细节**，应调用各 target 的状态判定函数。
4. **清理要在每个程序之后**：任务完成后确认进程退出；若卡住则超时后强制清理（需提权）。
5. **前置条件检查**：ok-ww 的任务要求游戏「在大世界并在队伍中」，否则会卡在等待态。**编排层应在启动前检查游戏状态**，否则必然卡死。
6. **全局超时**：每个程序配超时；整个编排也配总超时。

**建议的编排形态**：

```
for target in 配置的顺序:
    检查前置条件（游戏状态等）
    启动 target.exe
    等待第二层就绪（带超时）
    导航到任务页
    点击「开始」
    循环: 判定状态（完成/运行中/等待/异常）直到 完成 或 超时
    清理（确认退出；必要时强制）
    记录结果
```

**✅ 已实现（2026-10-16）**：上面这个形态已落到
`orchestrator/steps/main.py` 的 `--target both`（见 HANDOFF §8 模块划分）。

两个关键实现选择，都有实测依据：

1. **两轮各用子目录**（`<root>/ww`、`<root>/nte`）。若共用目录，
   两轮的节点号完全相同（都叫 `step8.log`），**后一轮会覆盖前一轮**，
   事后分不清哪份日志属于哪个程序。`state.json` 同理（`program` 键只能存一个值）。
2. **一个程序失败不影响另一个继续**。用户裁定可无人值守：
   若 ok-ww 因「今日已完成」异常退出，ok-nte 仍应照跑。
   单程序失败时 `both` 的退出码仍非 0（供脚本判断），但不会中断串联。

⚠️ **不要以为 `both` 是并发**：两程序沿用 INV-15 的独占前提，**串行**执行，
且每轮各自独立计 30 分钟上限（不是共享一个总上限）。

✅ **端到端实证（2026-10-16，`run-both-final`）**：`--target both --pre-clean`，**EXIT=0**，全程 16.4 分钟。

| 轮 | 结果 | 用时 | 节点 8 |
| --- | --- | --- | --- |
| 1 ok-ww | 8/8 全过 | 4.8 分钟 | **268.3s completed**（日志终止标记） |
| 2 ok-nte | 8/8 全过 | 11.6 分钟 | **620.7s completed**，`success` **7 项**、`failed=[]`、`skipped=['异象追猎']` |

**末尾的「串联复检」段**（本块新增）当轮就抓到了 ok-nte 的 launcher 残留：
`ok-nte 游戏 1 个 [('NTEGame.exe', 59272)]`，并给出清理指引 ——
对比旧行为（只报「程序 0 个」让人以为全干净），这正是复检存在的意义。

### 9.1 GUI 的目标选择器

**2026-10-18 改版**：从控制条上的单项下拉框（`TARGET_CHOICES` / `TARGET_ARG`，已删除）
改为**左栏顶部的多选清单** —— 需求是「目标程序可任意多选，且提供全选」。

| 控件 | 传给 `steps/main.py` |
| --- | --- |
| `跟随上次记录（不传 --target）`（默认勾） | **不传** `--target` |
| 勾 ok-ww / ok-nte（任意组合，顺序 = 清单声明顺序） | `--target ww` / `--target nte` / `--target ww,nte` |
| `全选` / `清空` | 批量设置上面那一列（全选 = `--target ww,nte`） |
| 一个都不勾 | **拒绝启动** + 清单下方红字告警 |

⚠️ **一个都不勾 ≠ 全部**。省略 `--target` 的语义是「跟随记录」，把空选当全选
是那种「跑完才发现跑错了程序」的静默失效。

⚠️ **「跟随记录」必须不传 `--target`**：它配合「接着上次」（`--resume`）续跑，
此时目标由记录决定。若图省事写成 `args += ["--target", "ww"]`，
**续跑 ok-nte 会被悄悄改回 ok-ww** —— 又一个静默失效。

⚠️ **跟随中勾一个程序会自动关掉跟随**（`App._on_target_chk`）。不自动关的话，
界面显示「已勾 ok-ww」但实际仍按记录跑，用户会认定「勾选不灵」。

清单来源是 `gui/targets.py`：用 `ast` **静态读** `orchestrator/programs.py` 的
`Program(key=..., display=...)` 与 `ALL = [...]` 顺序（**不 import、不执行**），
读不出来就回落 `FALLBACK` 并在界面告警 —— 与 `gui/chain.py` 同一笔交易：
**GUI 是跳板**，节点代码或主控坏掉时还得能打开界面去改它。

**每行行尾的进度点**是该程序**正在跑的那一轮**的进度（`○` / `▶ 3/8` / `3/8` /
`✓ 8/8` / `✖ 2/8`），与勾选无关；**点目标行**（不是勾选框）把下方步骤列表
切到该目标，串联时这是唯一能来回看两套节点状态的地方。
`StateWatcher` 因此改成了**多目标**：同时扫 `<root>/state.json` 与
`<root>/<target>/state.json`（串联时根目录没有 state.json，两轮各自一份），
`poll()` 返回 `{target: raw}`，`bus.node` 事件带 target。

验证：`probe/_probe_gui_target_wire.py`（用 Tk 的 API 直接调**真实的 `on_run`**，
把 `Runner` stub 掉看拼出的 argv）—— **不要靠人肉点击复核**，原因见 §10.7。

✅ **GUI 端到端实证（2026-10-17，`run-20261017-140330`）**：
上面那个探针只证明「argv 拼对了」，**不证明 GUI 能真的把链跑起来**。为此新增
`probe/_probe_gui_both_live.py`：建**真的** `App`（真窗口、真 `Runner`、真
`StateWatcher`），把目标清单**全选**（当年那版是下拉框的「两个都跑」），调**真实的 `App.on_run()`**，
再由探针自己抽 Tk 事件循环、收集 bus 上的日志与节点状态。

结果 **8/8 核对项通过、EXIT=0**，全程 759.5s：

| 轮 | 结果 | 用时 | 节点 8 |
| --- | --- | --- | --- |
| 1 ok-ww | 8/8 全过 | 258s | `completed`（终止标记；`hwnd=789000`，1458x800 @(495,417)）|
| 2 ok-nte | 8/8 全过 | 499s | `completed`，`success=['一咖舍','影院约会','喷泉签到','异象家具','羁遇赠礼'] failed=['日常领取'] skipped=['异象界域','异象追猎']` |

日志里逐条出现 `--target both` / 「串联第 1 轮」/「串联第 2 轮」/「串联汇总」/
「串联复检」，且**两轮各有一套 all-ok 的节点状态**。

⚠️ 两个**探针自身的坑**（都已修，写下来免得再踩）：

1. **不能只看 bus 推来的节点状态**。`bus.node` 只在**状态变化**时触发，而短跑
   （`--dry-run` 约 2.5s）会在 Tk 的 `after` 轮询第一次跑起来**之前**就结束，
   于是收集到的 `nodes` 恒为空 —— 实测干跑那次 `nodes` 实得 0 组 ok，但
   `state.json` 里 `ww`/`nte` 都是 `{'1':'ok'}`。**权威来源是落盘的 `state.json`**。
   这与 FAULT #18/#20/#27 同一形状：**单看一个信号就下结论，必然误判**。
2. **ok-ww 侧出现 67 次 `[INV-13] 本轮抓帧失败：帧几乎全黑`，那不是故障**。
   时序显示它**与正常帧交错出现**（指纹 40.00 → 全黑 → 105.55/107.15 → 全黑 →
   140.70/167.13），是游戏窗口在 ok-ww 的转场/加载瞬间短暂不可抓；框架如实报
   INV-13 后继续采样，任务最终正常完成。⇒ **黑帧本身不等于失败，要看它是否恢复**。

✅ **真机实证（2026-10-18 14:06:41，`run-20261018-140641`）**：这是 **FAULT #37 修好之后
第一次由用户亲手在 GUI 里点「两个都跑」**（不是探针、不是脚本），两轮全绿：

| 轮 | 结果 | 用时 | 节点 8 |
| --- | --- | --- | --- |
| 1 ok-ww | 9/9 全过 | 274s | `completed`（`终止标记=True 日常结束=True 杀游戏=False`；`hwnd=722750`，1458x924，身份 1.0000）|
| 2 ok-nte | 9/9 全过 | 674s | `completed`，`success=['异象界域','一咖舍','日常领取','影院约会','喷泉签到','异象家具','羁遇赠礼'] failed=[] skipped=['异象追猎']` |

- 程序侧日志对得上：ok-ww `14:11:04 Successfully Executed Task` → `14:11:14 quit app`；
  ok-nte `14:13:07 开始执行日常任务` → `14:22:16 结束执行日常任务`。
- **全程没有 `PermissionError`、也没有重试日志**：GUI 每 120ms 读 `state.json` 的抢锁
  在这一轮没有造成失败（`save()` 只在**重试用尽**时才抛，撞车但重试成功是静默的）。
- 串联复检：ok-ww 程序 0 / 游戏 0；ok-nte 程序 0、游戏 1 个 `NTEGame.exe`（pid 6884）——
  这是 FAULT #31 的**既有行为**（launcher 不自杀），不是回归；要清就跑 `--target both --pre-clean`。

---

## 10. 工作方式建议（血泪教训）

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
     配合 `docs/_probe_gui2_visual.py` 等自检。

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

## 11. 关键产物索引

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
> （依据 [README-ORCHESTRATOR.md](./README-ORCHESTRATOR.md) §7）。保留作**证据追溯**，
> 不参与生产流程。核心模块（`capture.py`、`template_probe.py`、`nte_main.py`）仍在 `probe/`。

