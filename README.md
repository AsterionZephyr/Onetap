# Onetap

**在进程外、以真实光标、黑盒地操作 ok-ww / ok-nte / MaaEnd 完成日常任务。**

三个目标程序都是**他人项目**：本仓库**不改造其源码**，只观察它们的窗口、按图像定位元素、发送真实鼠标点击，
并**如实报告**每一个程序的结果 —— 证据不足时报 `UNKNOWN`，绝不默认成功。

> 根目录只放本文件与 [AGENTS.md](./AGENTS.md)（新会话必读），**其余文档全部在 [`docs/`](./docs/)**。

---

## 这是什么

| 层 | 内容 |
| --- | --- |
| **编排** | **每个程序一份节点链**（清单在 `orchestrator/apps/<key>/nodes/__init__.py`）：提权检查 → 启动 → 等窗口 → 等就绪 → 抓首帧 → 置前台 → 跑任务 → 清理（节点 3 不存在；MaaEnd 的节点 5/6 是专属节点）。按 `--target` 串联多个程序 |
| **专项** | 每个程序一个包（`apps/<key>/`）：该程序**自己的节点清单** + 定位 + 身份证据 + 终态判据 + 专属节点 |
| **GUI** | 两页跳板：一页**跑**（步骤状态 + 输出日志），一页**改**（点节点改源码、即时保存重跑） |
| **证据** | `probe/` 一次性探测脚本 + 不变量与实测记录（[`docs/FRAMEWORK.md`](./docs/FRAMEWORK.md) / [`docs/HISTORY.md`](./docs/HISTORY.md)） |

**节点数量、编号、顺序随程序** —— 主控与 GUI 都只按该程序自己的清单执行，没有全局链条：

```powershell
python -X utf8 -m orchestrator.steps.main --list    # 按程序逐份打印链条（顺序 = MaaEnd → ok-ww → ok-nte）
python -X utf8 -m orchestrator.steps.main --target zmd|ww|nte|all
```

当前只有 MaaEnd 用到专属节点（5 = 等自我更新收敛、6 = 点掉更新弹窗、8 = 任务流）；
ok-ww / ok-nte 的节点 5/6 用共用节点，只有节点 8 专属。为什么这么拆见
[ADR 0005](./docs/adr/0005-per-program-node-chain.md)。

---

## 核心原则

| 原则 | 含义 |
| --- | --- |
| **黑盒** | 不改目标程序源码，只做窗口截屏 + 真实鼠标点击 |
| **真实光标** | `SetCursorPos` + `SendInput`；**不用** `PostMessage`（UIPI 会拒绝） |
| **独占** | 同一时间只跑一个目标；开始前清理残留进程 |
| **如实报告** | 四种终态 `SUCCESS` / `FAILED` / `TIMEOUT` / `UNKNOWN`，`UNKNOWN` 是特性不是 bug |
| **不检查游戏状态** | 直接启动程序并点击，游戏由用户自行准备 |

这些规矩的每一条背后都有实测教训（静默失效：不抛异常、不返回错误码，只给错误结果），
详见 [`docs/HANDOFF.md`](./docs/HANDOFF.md) §2 与 [`docs/FRAMEWORK.md`](./docs/FRAMEWORK.md) 的不变量清单（INV-*）。

---

## 目录

| 路径 | 内容 |
| --- | --- |
| `orchestrator/` | 正式实现：引擎 + 共用节点 + 每程序清单与专属节点，另有基础设施（抓帧 / 输入 / 窗口 / 匹配） |
| `orchestrator/apps/` | 每程序一个包（`ww/` / `nte/` / `zmd/`）：该程序的**节点清单**（`nodes/__init__.py`）、定位 + 身份证据 + 终态判据、专属节点 —— **改某个程序只改这里** |
| `orchestrator/steps/` | 引擎（`main.py` / `context.py` / `chain.py`）+ **共用节点**（`common/stepN_*.py`，节点 8 骨架是 `common/push.py`）；可 `--from` / `--only` 单跑 |
| `gui/` | 两页 GUI（运行页 / 节点代码页） |
| `launcher/gui.bat` | 双击启动 GUI（自助提权），从自身位置向上找仓库根 |
| `templates/` | 图像资产 + `assets.json`（模板 + 比例位置 + 出生尺寸 + 用途） |
| `probe/` | 一次性探测脚本（**证据来源，不是产品代码**）—— 索引见 [`probe/README.md`](./probe/README.md) |
| `docs/` | **全部文档**：规范 / 手册 / 判定 / GUI / 历史 / 故障流水 / ADR |
| `legacy/` | 旧版编排器与历史探测记录（保留作证据） |
| `logs/` | 运行日志与抓帧落盘（**不入库**，见 [`docs/VERDICT.md`](./docs/VERDICT.md) 的清理策略） |

---

## 环境要求

| 项 | 值 |
| --- | --- |
| **Python** | 3.13（本机实测 `D:\WORKs\Anaconda\python.exe`） |
| **依赖** | Pillow、numpy、pywin32 |
| **不可用** | cv2 / pyautogui / mss —— **不要引入** |
| **权限** | **必须管理员**：三个目标程序都是 `requireAdministrator`，非提权会话连杀进程都会被拒 |
| **平台** | Windows（Win32 API + 屏幕抓图） |

---

## 快速开始

**GUI（推荐）**：双击 `launcher/gui.bat`，它会自助请求提权。

**命令行**：

```powershell
# 串联跑 ok-ww -> ok-nte（开始前清理残留进程）
python -X utf8 -m orchestrator.steps.main --target ww,nte --pre-clean

# 只跑一个程序
python -X utf8 -m orchestrator.steps.main --target zmd --pre-clean

# 只校验与定位，不启动、不点击
python -X utf8 -m orchestrator.steps.main --dry-run

# 单跑某个节点（改完代码秒级验证，不必从头重跑整条链）
# 编号 = 该程序自己清单里的节点编号
python -X utf8 -m orchestrator.steps.main --only 8
python -X utf8 -m orchestrator.steps.main --from 6
```

参数全表、`--target` 语义、`state.json` 契约、排障流程见 [`docs/RUNBOOK.md`](./docs/RUNBOOK.md)。

---

## 文档

**除本文件与 [AGENTS.md](./AGENTS.md) 外，全部在 [`docs/`](./docs/)。** 按「想干什么」挑一份：

| 文档 | 回答什么问题 |
| --- | --- |
| [docs/FRAMEWORK.md](./docs/FRAMEWORK.md) | **规范**：不变量（INV-*）、目标程序差异一览、链条结构 —— **断言冲突时以它为准** |
| [docs/HANDOFF.md](./docs/HANDOFF.md) | **实现交接**：静默失效全表、十二条硬性规则、陷阱、模块划分、产物索引 |
| [docs/RUNBOOK.md](./docs/RUNBOOK.md) | **怎么跑**：GUI / 命令行参数、单节点重跑、续跑、`state.json`、排障 |
| [docs/VERDICT.md](./docs/VERDICT.md) | **完成判定**（三程序终态口径）+ 日志窗口 + **清理策略** |
| [docs/GUI.md](./docs/GUI.md) | GUI 手册：两页各干嘛、目标多选器、自检记录、未提权会怎样 |
| [docs/CONTEXT.md](./docs/CONTEXT.md) | **领域术语表**（窗口持有者、匹配锚点、动作前置关、完成帧、静默失效……） |
| [docs/HISTORY.md](./docs/HISTORY.md) | **实测与历史**：各阶段实测、工具环境、0.1 版与旧编排层记录、ok-ww 窗口事实附录 |
| [docs/FAULT-LOG.md](./docs/FAULT-LOG.md) | **故障流水账**：每次踩坑的现场、归因与修复 |
| [docs/adr/](./docs/adr/) | **决策记录**：0001 黑盒真实光标 / 0002 锚点组合与联合唯一性 / 0003 每程序专项模块 / 0004 Tkinter 而非 Web / 0005 节点链属于每个程序 / 0006 工作区目录契约 / 0007 文档分层与单一事实源 |
| [AGENTS.md](./AGENTS.md) | 新会话必须知道、否则会做错的约定（目录、动手前、静默失效、硬性规则） |
| [legacy/README.md](./legacy/README.md) | 旧版编排器与历史探测记录（证据，不在产品路径上） |

---

## 免责声明

本项目只用于本机个人自动化：它操作的是**他人开发**的游戏辅助程序，仓库不含这些程序的源码或资源，
也不分发游戏文件。使用前请自行确认符合相关程序与游戏的用户协议。
