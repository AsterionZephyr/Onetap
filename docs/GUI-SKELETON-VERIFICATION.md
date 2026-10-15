# 两页 GUI · 自检记录

> 对 `gui/` 包的三组验证：**48 项断言全部通过**，每项都留可复现命令。
> 全部**无头**（除视觉复核），不启动 ok-ww、不点击屏幕。

相关：[GUI-README.md](../GUI-README.md)（使用手册）、
[GUI-DEPENDENCY-DECISION.md](./GUI-DEPENDENCY-DECISION.md)（选型）、
[STEPS-README.md](../STEPS-README.md)（节点链）。

---

## 1. 两页界面（30 项）

```powershell
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_gui2_selftest.py
```

| 组 | 验证内容 | 结果 |
| --- | --- | --- |
| 1 | 步骤清单与 `steps/` 一致（含与 `main.py` 的 `CHAIN` 比对）、节点号无 3、8 个文件都在 | ✅ 3/3 |
| 2 | App 构建、**两页**、两页各 8 行步骤、**左右 weight=(1,4) 即 1/5** | ✅ 6/6 |
| 3 | 日志分级 `node/ok/warn/err`、顶端"当前步骤 6 · …"、节点行切 running/failed、横幅逻辑 | ✅ 5/5 |
| 4 | 点选→载入→**保存往返一致**→保留结尾换行→重新载入丢弃改动→内容与原文件一致 | ✅ 10/10 |
| 5 | 增量高亮 == 全量（前 21 行）、增量比全量快 39×、增量 3.5ms | ✅ 3/3 |
| 6 | **运行中禁止保存**（0 次写入 + 有警告）／不运行时可保存（1 次写入） | ✅ 3/3 |
| 7 | 载入路径限定在 `steps/` 下且是 `.py` | ✅ 2/2 |

第 6 组有**反向对照**：如果只测"运行中不写入"，一个永远不写入的实现也能通过；
所以同时验证"不在运行时会写入"，证明守卫真的在起作用。

---

## 2. 子进程驱动（18 项）

```powershell
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_gui2_runner.py
```

```
1. 起子进程跑 `main.py --list`
  [OK]   退出码为 0  code=0
  [OK]   收到了输出  13 行
  [OK]   链条里含节点 1 / 节点 9 / 说明无节点 3
  [OK]   子进程已结束
2. `--only` 参数能透传
  [OK]   非法节点被拒绝  code=1
  [OK]   给出了可读错误  --only 99 不在链条中：['1','2','4','5','6','7','8','9']
3. 停止：整树终止
  [OK]   stop() 报告了结果  已终止进程树 (pid 10012)
  [OK]   子进程确已终止  returncode=1
  [OK]   is_running() 变为 False
  [OK]   tasklist 里已无此 pid
4. StateWatcher 读真实的 state.json
  [OK]   读出了 state.json，7 个节点
  [OK]   首次轮询推送了状态  7 条
  [OK]   mtime 未变时不重复推送  0 条
```

第 4 组用的是**真实历史运行** `logs/runs/run-20261006-014118/state.json`。

---

## 3. 高亮性能

```powershell
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_gui2_perf.py
```

| 行数 | 全量 | 增量 | 提速 |
| --- | --- | --- | --- |
| 200 | 10.8 ms | 1.06 ms | 10× |
| 400 | 37.6 ms | 1.88 ms | 20× |
| 800 | 157.8 ms | 3.48 ms | 45× |
| 2000 | 965.3 ms | 8.11 ms | 119× |

增量与全量**逐 tag 一致**（`True`）。全量是 O(n²)，所以打字时只走增量。

---

## 3.1 清单漂移守卫（非空测）

```powershell
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_gui2_drift.py
```

"启动时比对清单与磁盘"这条如果永远返回"没问题"，就等于没有检查。
所以人为制造两种漂移，确认**都会报警**：

| 场景 | 结果 |
| --- | --- |
| 基线 | 0 处问题 |
| 只改 `steps/main.py` 的 `CHAIN`（模块名） | ✅ 报"**不一致**"，并**列出两边清单**逐项对照 |
| 目录里多出未登记的 `step99_bogus.py` | ✅ 报"目录里有清单未登记的节点文件" |
| 还原后 | 0 处问题 |

⚠️ 前两次尝试用 PowerShell 的 `-replace` 改文件，**把编码搞坏了**，
于是走到了"SyntaxError 分支"而不是"不一致分支" —— 报告看着像通过，
其实没测到目标路径。改成用 Python 改文件后编码可控，才真正验证到。
（这是本项目第四次「**观测为真、归因错误**」的同类风险。）

---

## 4. 视觉复核（肉眼看）

依项目自身原则「抓图必须落盘供肉眼复核」（HANDOFF §10.5），GUI 也必须看图。

```powershell
& "D:\WORKs\Anaconda\python.exe" -X utf8 docs\_probe_gui2_visual.py 30
```

截图：[gui2-p1.png](./gui2-p1.png)（第 2 页，含代码编辑器）

| 元素 | 观察结果 |
| --- | --- |
| 两个页签 | ✅ 「运行」/「节点代码」 |
| 左列步骤列表 | ✅ 序号 `1 2 4 5 6 7 8 9` 等宽灰底，**像代码行号**；无节点 3 |
| 左列宽度 | ✅ 约占 1/5 |
| 第 1 页日志顶端 | ✅ 「当前步骤 6 · 抓首帧并校验 · 失败」（失败时转红） |
| 日志配色 | ✅ 节点行蓝、`[OK]` 青、`[警告]` 黄、`[INV-12]` 红 |
| 步骤状态点 | ✅ `–` 跳过 / `✔` 完成 / `✖` 失败 / `○` 未运行 |
| 第 2 页代码 | ✅ 行号 1–45、关键字蓝粗、字符串红、注释绿斜、数字青 |
| 第 2 页高亮选中行 | ✅ 节点 6 整行淡蓝底 |
| 保存按钮位置 | ✅ **右下角**（旁边是「放弃修改」） |
| 文件标识 | ✅ `节点 6 · 抓首帧并校验 — orchestrator/steps/step6_first_frame.py (154 行)` |

---

## 5. 实现过程中修掉的两个真实缺陷

都不是"测试写错"，是代码本身的问题：

### 5.1 `_apply_tags` 是 O(n²)（导致自检挂死）

第一版判断"某位置是否在注释里"用的是对 `comment_spans` **线性扫描**：

```python
def in_comment(s):
    return any(a <= s < b for a, b in comment_spans)   # ← 每个匹配都扫一遍
```

`_apply_tags` 里每个正则匹配都调它一次 ⇒ 整体 O(n²)。400 行文件就能让
自检**永久挂住**（不是慢，是不返回）。

**修法**：在已排序的 span 上二分（`bisect_right`）。修完 2000 行全量
965ms、增量 8ms。

### 5.2 自检里的模态对话框死锁

`on_save()` 在"运行中"会调 `messagebox.showwarning` —— 那是**模态**对话框，
无头环境没人点"确定"，自检**永远挂在那里**。

**修法**：自检里把 `gui.app.messagebox` 换成不弹窗的桩。
⚠️ 这是**测试**的坑，不是产品缺陷；但它说明一条：**无头测 GUI 必须先把
所有模态对话框打桩**，否则会得到"卡住"这种极难定位的症状。

---

## 6. 停止语义的对照实验

第一版自检用 `os.kill(pid, 0)` 判断进程是否真的被杀，**误报为失败**。
单独做了对照（`docs/_probe_gui2_stop.py`）：

```
起子进程 pid=64996
  tasklist 命中（杀之前）: True
  Popen.poll()            : None
stop() -> 已终止进程树 (pid 64996)
  Popen.poll()            : 1        ← 已退出
  tasklist 命中（杀之后）  : False    ← 系统视角确实没了
```

⇒ `taskkill /T /F` **工作正常**。Windows 上 pid 在 `Popen` 回收前仍可能
被 `os.kill(pid,0)` 命中，所以判据应当用 `Popen.poll()` / `tasklist`。

---

## 7. 已知限制（如实记录）

| # | 限制 | 说明 |
| --- | --- | --- |
| 1 | 无帧预览 | 抓图在 `logs/runs/<run>/shots/`，用资源管理器看。旧骨架有预览，需要可加回（`PIL.ImageTk`） |
| 2 | 高亮不理解 Python 语法 | 多行字符串、f-string 嵌套都按正则处理。**任何输入都不会抛异常** —— 这是刻意的 |
| 3 | 无查找替换 / 跳转定义 | 见 GUI-DEPENDENCY-DECISION §5.4.3 的诚实清单 |
| 4 | ~~不自提权~~ **已变更** | 当时（骨架期）：常驻横幅 + `Start-Process -Verb RunAs`（GUI-README §2）。**后来已改为入口自动弹 UAC** —— 见 GUI-README §2 与 `gui/elevate.py` |
| 5 | 步骤清单两处声明 | `gui/chain.py` 与 `steps/main.py` 的 `CHAIN`。**启动时自动比对并警告**，是刻意的摩擦 |
| 6 | 运行时禁止保存 | 有意为之（防半文件竞态），不是缺陷 |
