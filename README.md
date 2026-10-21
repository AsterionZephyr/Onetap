# Onetap

**在进程外、以真实光标、黑盒地操作 ok-ww / ok-nte / MaaEnd 完成日常任务。**

三个目标程序都是**他人项目**：本仓库**不改造其源码**，只观察它们的窗口、按图像定位元素、发送真实鼠标点击，
并**如实报告**每一个程序的结果 —— 证据不足时报 `UNKNOWN`，绝不默认成功。

---

## 这是什么

| 层 | 内容 |
| --- | --- |
| **编排** | 一条**九节点链**（提权检查 → 启动 → 等窗口 → 等就绪 → 抓首帧 → 置前台 → 跑任务 → 清理），按 `--target` 串联多个程序 |
| **专项** | 每个程序一个模块，负责该程序的定位、身份证据、终态判据 |
| **GUI** | 两页跳板：一页**跑**（步骤状态 + 输出日志），一页**改**（点节点改源码、即时保存重跑） |
| **证据** | `probe/` 一次性探测脚本 + `FRAMEWORK.md` 不变量与实测记录 |

三个程序全部接入同一条链：

```
--target zmd|ww|nte|all      串联顺序 = MaaEnd → ok-ww → ok-nte
```

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
详见 [HANDOFF.md](./HANDOFF.md) §2 与 [FRAMEWORK.md](./FRAMEWORK.md) 的不变量清单（INV-*）。

---

## 目录

| 路径 | 内容 |
| --- | --- |
| `orchestrator/` | 正式实现：共用九节点链 + 基础设施（抓帧 / 输入 / 窗口 / 匹配） |
| `orchestrator/apps/` | 每程序专项模块（`ww.py` / `nte.py` / `zmd.py`）——**改某个程序只改这里** |
| `orchestrator/steps/` | 断点式节点脚本（`main.py` 为入口，可 `--from` / `--only` 单跑） |
| `gui/` | 两页 GUI（运行页 / 节点代码页） |
| `launcher/gui.bat` | 双击启动 GUI（自助提权），从自身位置向上找仓库根 |
| `templates/` | 图像资产 + `assets.json`（模板 + 比例位置 + 出生尺寸 + 用途） |
| `probe/` | 一次性探测脚本（**证据来源，不是产品代码**） |
| `docs/` | ADR、GUI 选型与自检记录、阶段性实现文档 |
| `legacy/` | 旧版编排器与历史探测记录（保留作证据） |
| `logs/`、`probe-shots/` | 运行日志与抓帧落盘（**不入库**） |

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
python -X utf8 -m orchestrator.steps.main --only 8
python -X utf8 -m orchestrator.steps.main --from 6
```

---

## 文档

| 文档 | 回答什么问题 |
| --- | --- |
| [HANDOFF.md](./HANDOFF.md) | 实现交接书：十二条硬性规则、六类静默失效、十八个陷阱、三程序对照表 |
| [FRAMEWORK.md](./FRAMEWORK.md) | **不变量（INV-*）** + 各阶段实测记录（断言冲突时以它为准） |
| [CONTEXT.md](./CONTEXT.md) | 领域术语表（窗口持有者、匹配锚点、动作前置关、完成帧、静默失效……） |
| [COMPLETION-VERDICT.md](./COMPLETION-VERDICT.md) | 完成判定：以目标程序的任务日志阶段序列裁决 |
| [CLEANUP.md](./CLEANUP.md) | 清理策略：按进程血缘强制清理 |
| [ORCHESTRATION.md](./ORCHESTRATION.md) | 编排层实现记录与实测结果 |
| [README-ORCHESTRATOR.md](./README-ORCHESTRATOR.md) | 编排框架使用手册（怎么跑、跑什么、出问题看哪里） |
| [STEPS-README.md](./STEPS-README.md) | 断点式编排：节点与文件对照、单节点怎么跑 |
| [GUI-README.md](./GUI-README.md) | GUI 使用手册（两页各干嘛、未提权会怎样） |
| [docs/adr/](./docs/adr/) | 决策记录（黑盒真实光标、锚点组合与联合唯一性、专项模块拆分） |
| [AGENTS.md](./AGENTS.md) | 新会话必须知道、否则会做错的约定 |

---

## 免责声明

本项目只用于本机个人自动化：它操作的是**他人开发**的游戏辅助程序，仓库不含这些程序的源码或资源，
也不分发游戏文件。使用前请自行确认符合相关程序与游戏的用户协议。
