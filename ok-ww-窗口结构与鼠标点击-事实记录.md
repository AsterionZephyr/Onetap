# ok-ww 窗口结构与鼠标点击 — 事实记录

> 实测日期：2026-10-01。只记录**实测事实**，不含推测与建议。
> 测量环境：Windows 11（Build 26200），本机 DPI 缩放 1.25×，ok-ww v3.6.7。

---

## 一、ok-ww 的窗口结构

```
ok-ww.exe  (Tauri 外壳，启动后退出/隐藏)
  └─ pythonw.exe   pid=52140  400MB      ← 真正的应用，窗口持有者
       hwnd=9834000
       class = Qt6111QWindowIcon
       title = 'OK-WW v3.6.7 China  - OK-WW'
       尺寸  = 1200x800（首次）/ 1375x900（1.25x DPI 下）
       children = 0                        ← 零子窗口，纯 Qt 自绘
```

**实测结论：**

1. **`pythonw.exe` 不是孤儿，是真正干活的进程。** `ok-ww.exe`（Tauri 外壳）启动后退出或转后台，窗口由 `pythonw` 持有。按进程名清理时必须保留 `pythonw`。

2. **窗口标题是长串，不是 `'OK-WW'`。** 框架对字符串 title 做**精确相等**比较，`'OK-WW'` 匹配不上 `'OK-WW v3.6.7 China  - OK-WW'`；非 str 才走 `re.search`，所以必须编译成正则。

3. **零子窗口 + 纯自绘。** 没有可定位的按钮句柄，也没有标准控件树。

4. **窗口尺寸会变。** 实测同一窗口先后出现 `1375x1000`、`1200x800`、`1375x900`。
   抓图与点击若跨了尺寸变化，**算出的点击坐标就是错的**。
   实测反例：1372 宽的模板在 1375 宽的帧里匹配成功，但窗口实际只有 1200 宽。

**DPI 缩放**：本机为 1.25×。窗口逻辑尺寸 1100×720 时，实际 rect 为 1375×900。抓图与坐标换算必须考虑这一点。

---

## 二、鼠标点击

### 2.1 两套方式的实测对照

| 方式 | 机制 | 实测结果 |
| --- | --- | --- |
| `PostMessage` | `win32gui.PostMessage(hwnd, WM_LBUTTONDOWN/UP, ...)` | 从**非提权**会话向提权的 ok-ww 投递 → `(5, 'PostMessage', '拒绝访问。')` |
| 真实光标 | `SetCursorPos` + `SendInput` | ✅ 成功移动光标 |

### 2.2 UIPI 是关键约束

Windows **UIPI**：低完整性进程不能向高完整性窗口投递窗口消息。

| 场景 | PostMessage |
| --- | --- |
| 提权程序 → 提权窗口 | 允许 |
| 非提权程序 → 提权窗口 | **被拒（Access denied）** |
| 任意 → 同/低完整性窗口 | 允许 |

**真实光标（`SendInput`）走输入队列，不受 UIPI 限制** —— 这是它与 PostMessage 的本质区别。

ok-ww 是 `requireAdministrator`，由此得到三个实测事实：

- **操作方必须以管理员运行**，否则 PostMessage 被拒
- 非提权脚本**无法**向它投窗口消息
- 非提权会话**也杀不掉它**（实测 `Stop-Process` → Access denied）

### 2.3 「窗口必须在前台」的实际后果

`Pynput` 方式的 `should_capture()` 等价于 `hwnd_window.is_foreground()`，
即要求 `GetForegroundWindow() == hwnd`。

**这不只是"要求"，它会让上游框架整个卡死**（实测）。
框架 `TaskExecutor.sleep()` 的分支：

```python
if not (self.paused or ... or not self.interaction.should_capture()):
    to_sleep = self.pause_end_time - time.time()
    if to_sleep <= 0:
        return                      # ← sleep() 唯一的正常出口
else:
    self._wait_for_activity(0.1)    # ← should_capture()=False 时走这里，无出口
```

窗口不在前台 → `should_capture()` 为 False → 走 `else` → **`sleep()` 永不返回**
→ `execute()` 主循环第一步即卡住 → **队列里的任务永远不被取出**。

**用户可见症状：点「开始」后毫无反应，且没有任何报错。**
线程真栈（实测抓取）：

```
execute      → sleep(1)
sleep        → _wait_for_activity(0.1)
_wait_for_activity → condition.wait(timeout)
```

同时 `paused=False`、`thread_alive=True`、`queue=1[...]` 连续 90 秒不变。

`PostMessage` 的 `should_capture()` 恒为 `True`，**不触发**此问题。

### 2.4 点击坐标

- 框坐标来自**抓图帧**，经 `ClientToScreen` 转为屏幕坐标。
- **帧尺寸必须等于窗口尺寸**，否则坐标错位（见第一节的尺寸变化问题）。
- 框内点击位置用**比例**表达：`relative_x` / `relative_y`，
  `0.5` = 居中，`0.85` = 靠右。
- 比例比像素偏移更稳 —— 不受模板尺寸与窗口缩放影响。

### 2.5 其他实测事实

- **真实光标会移动鼠标**，且目标窗口需在前台。
- 提权环境下会额外出现一条报错（与识别无关、不影响功能）：
  `pywintypes.error: (5, 'GetCursorPos', '拒绝访问。')` —— 来自无边框窗口插件取光标位置被拒。
