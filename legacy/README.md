# legacy — 过时产物

**这里的文件都不参与生产流程。** 保留它们是为了**证据追溯**：其中多数是
[HANDOFF.md](../HANDOFF.md) / [FRAMEWORK.md](../FRAMEWORK.md) 中实测结论的原始依据。

> 移动日期：2026-10（本次整理）。全部用 `git mv` 迁移，**历史可追**。

## 当前生效的实现（与之对照）

| 路径 | 状态 |
| --- | --- |
| [`orchestrator/steps/`](../orchestrator/steps/) | ✅ **当前链条**（九节点拆分） |
| [`orchestrator/`](../orchestrator/) 包（除 `gui.py`） | ✅ 当前模块（`window`/`capture`/`match`/`input` 等） |
| [`gui/`](../gui/) | ✅ 当前 GUI（两页、子进程驱动、可编辑） |
| [`probe/`](../probe/)（9 个核心模块 + 3 张活帧） | ✅ 生产代码与离线样本 |

---

## code-old-orchestrator/ — 旧版编排器

| 文件 | 过时依据 |
| --- | --- |
| `orchestrator.py` | [STEPS-README.md](../STEPS-README.md) §8 列为「**旧版**」。功能已被 `steps/` 的九节点链取代 |
| `targets.py` | 同上，旧版的配置中心；当前配置内联在 `steps/` 与 `orchestrator/assets.json` |

⚠️ 这两个文件原在 `probe/` 下，与其余探测脚本混在一起。它们是**完整实现**而非一次性探针，
故单独成目录。

## code-old-gui-skeleton/ — 旧版 GUI 骨架

| 文件 | 过时依据 |
| --- | --- |
| `gui.py` | [GUI-README.md](../GUI-README.md) §9：「**上一版的单页骨架**」，「本 GUI 取代它」。同进程开线程驱动旧 `Orchestrator.run()`，**没有代码编辑** |

⚠️ **它 import 旧版 `Orchestrator`**，因此**依赖上面 `code-old-orchestrator/` 才能运行**。
两者是一个整体，不要拆开使用。当前 `gui/` 不引用它（已核实）。

## probe-investigation/ — 一次性调查脚本

`*.py`（50 个）—— [README-ORCHESTRATOR.md](../README-ORCHESTRATOR.md) §7 定性：

> 其余 **50 个**脚本是开发期的**一次性调查工具**（`nte_sweep.py`、`page_map.py`、
> `anchor_*`、`t4_*`、`q3_*`、`taskbar_*` 等）。它们保留作为**证据追溯**，
> **不参与生产流程**，可以安全忽略。

按该节口径，`probe/` 的「核心 11 个」**全部留在原位未动**（含 `ww_action.py`、
`ww_verdict.py`、`nte_verdict.py`、`cleanup.py`、`capture.py`、`template_probe.py`、
`nte_main.py`、`pngout.py`、`refresh_assets.py`）。

### shots/ — 调查期抓帧（132 张 PNG）

这些是上述脚本的**输出**，用于肉眼复核（[HANDOFF.md](../HANDOFF.md) §10 第 5 条
「抓图必须落盘供肉眼复核」）。

⚠️ **三张活帧有意留在 `probe/`，未移动**：

| 文件 | 为什么不能动 |
| --- | --- |
| `probe/running-000.png` | `orchestrator/selftest.py` 的离线样本；被 [STEPS-README.md](../STEPS-README.md) §6 引用 |
| `probe/obs-000.png` | 同上（selftest 内置样本） |
| `probe/okww-now.png` | 同上（selftest 内置样本，负向样本） |

移动它们会**直接弄坏 `python -m orchestrator.selftest`** 与文档中的命令。

### orch-runs/ — 旧版编排器运行记录（34 个 JSON）

旧 `orchestrator.py` 每次运行写出的状态快照（[README-ORCHESTRATOR.md](../README-ORCHESTRATOR.md) §「每次运行写一份 JSON 到
`probe/orch/orch-YYYYMMDD-HHMMSS.json`」）。当前链条改用**运行目录 + `state.json`**，
不再写这里。

## assets/ — 已弃用资产

| 文件 | 过时依据 |
| --- | --- |
| `2_nte.png` | [templates/assets.json](../templates/assets.json) 明示：「旧版动作元素；**v1.4.8 起改为行结构扫描**」，`page` 字段标为「（已弃用）」 |

---

## 恢复方式

若需把某个文件移回原位：

```powershell
git mv legacy/<子目录>/<文件> <原路径>
```

原路径见本文各表。**注意 `code-old-gui-skeleton/gui.py` 必须与
`code-old-orchestrator/` 一起恢复**才能运行。
