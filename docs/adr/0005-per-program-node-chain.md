# 5. 节点链属于每个程序，不再是一条统一九节点链

日期：2026-10-22

## 状态

已接受，**已落地**：三个程序的链条各在 `orchestrator/apps/<key>/nodes/__init__.py`，
`orchestrator/steps/chain.py` 是唯一的读取入口，旧的 `orchestrator/steps/stepN_*.py`
（含 `step8_run_task.py`）已全部删除。本 ADR 只切链条清单的归属；
[ADR 0003](./0003-per-program-app-modules.md) 的「按程序切模块」仍然有效。

## 背景

在此之前，链条是**引擎的一份全局清单**：`orchestrator/steps/main.py` 里的 `CHAIN`
（1、2、4、5、6、7、8、9 八节，没有节点 3），`orchestrator/steps/context.py` 按它算下一步，
`gui/chain.py` 又抄了一份 `STEPS` 供界面显示。程序之间的差异只有两处出口：

- 节点 8 的 `body()` 里 `if prog.key == ...` 分派；
- 节点 5/6 允许程序专属文件（MaaEnd 的 `step5_wait_ready.py` / `step6_first_frame.py`）
  在共用骨架外包一层。

于是「三个程序跑同一条链」被写成了框架事实。但它其实是**三个程序的巧合**：
MaaEnd 的节点 5 要先等自我更新收敛（更新会在运行期间重启进程、换 hwnd），节点 6 要先
点掉「更新完成」模态框（它会压暗身份锚点），这两件事 ok-ww / ok-nte 都没有；ok-nte 的
任务页结构与 ok-ww 不同构，节点 8 的定位链完全不同。而「5/6 对 MaaEnd 是专属的」这件事，
在全局清单里只体现为一次分派，读清单的人看不出来。

更实际的代价在**加程序**：节点数量、编号、顺序只要有一点不同，就要改 `main.py` 的
`CHAIN`、`context.py` 的下一步计算，再同步 `gui/chain.py` 的第二份声明。
「这个程序跑哪几节」在代码里没有单一出处。

## 决策

1. **节点清单搬到程序目录**。每个程序在自己的 `orchestrator/apps/<key>/nodes/__init__.py`
   里用一份 `NODES` 字面量声明链条，元素是
   `Node(sid, name, label, why, has_args, shared)`。节点**数量、编号、顺序、每节用哪份
   实现**全在这一个文件里。共用节点也必须逐条写进每个程序自己的清单 —— 「这个程序跑哪
   几步」只有这一处可读，不在别处被偷偷追加。

2. **引擎只按清单执行，不再有全局 `CHAIN`**。`orchestrator/steps/main.py` 与
   `context.py` 只经 `orchestrator/steps/chain.py` 的 API 读清单：
   `chain(key)` / `ids(key)` / `by_id(key,sid)` / `module(key,node)` /
   `module_of(key,sid)` / `next_of(key,sid)` / `describe(key,sid)` / `check_all()`。
   `--list` 按程序逐份打印链条（顺序 = `programs.ALL` = MaaEnd → ok-ww → ok-nte）；
   `--only/--from/--to` 的编号是**该程序自己的 sid**，不在该程序清单里的编号直接拒绝。
   GUI 读**同一份磁盘清单**（`ast` 静态读，不 import 业务模块），不再有第二份 `STEPS`。

3. **不复制整套骨架，程序差异走钩子参数**。共用机制留在 `orchestrator/steps/common/`，
   且**不认识任何具体程序**（不出现 `ww` / `nte` / `zmd`）；差异由使用方以钩子传入：

   - 节点 5：`run(state, args, log, prog, pre_ready=None)`。`pre_ready` 返回 `None` 继续，
     返回 `(status, data, note)` 则直接收束 —— MaaEnd 用它做「等自我更新收敛」闸门，
     闸门位于 `require_hwnd` 之前（更新会重启进程换句柄）。
   - 节点 6：`run(state, args, log, prog, identity, pre_frame=None, identity_hint=None)`。
     `pre_frame` 在身份校验**之前**跑（点掉压暗锚点的弹窗），`identity` 换成本程序的
     身份证据，`identity_hint` 只改失败日志措辞 —— MaaEnd 用底部绿色「开始任务」按钮，
     hint 换成「多半被全屏游戏盖住」。
   - 节点 8：骨架 `steps/common/push.py` 的
     `run(state, args, log, prog, navigate, locate, wait, before_click=None, locate_note=None)`，
     四个必选钩子 + 两个可选钩子（`before_click(state, args, log, attempt)` 在每一轮点击前、
     `locate_note(info) -> str` 只改日志）。ok-ww / ok-nte 套骨架；MaaEnd 没有任务页与侧栏，
     整段用 `apps/zmd` 的 `zmd_run`，只借骨架的 `first_frame` 与参数。

4. **`chain_key` 是执行期自检，不是注释**。
   `context.run_step(step_id, name, body, extra_args=None, chain_key=None)`：程序专属节点
   必须传 `chain_key`，它拿清单校验「本文件 + 本节点」是否属于该程序，不符就打印
   `[!!]` 并返回 2，且**不污染 `state.json`**。调用方传的 `name` 是短名
   （`first_frame`），清单里是全名（`step6_first_frame`）—— 拼错同样被 `[!!]` 拒绝。

当前三份清单（`--list` 的原文来源）：

| 程序 | 节点 | 专属 |
| --- | --- | --- |
| ok-ww / ok-nte | 1, 2, 4, 5, 6, 7, 8, 9 | 只有节点 8（各自的 `apps/<key>/nodes/step8_run_task.py`） |
| MaaEnd（zmd） | 1, 2, 4, 5, 6, 7, 8, 9 | 节点 5、6（`has_args=True`）、节点 8 |

## 考虑过的替代方案

**继续 `main.py` 一份 `CHAIN`，差异用 `if prog.key` 分派**。被否：节点数、编号、顺序一变
就得改引擎；加程序仍然要去动共用文件；「这个程序跑哪几节」依旧没有单一出处。节点 8 内的
`if` 分派已经证明会被继续追加 —— MaaEnd 接入时三个共用文件各长出一段。

**每个程序复制整套骨架**（`steps/ww/`、`steps/nte/`、`steps/zmd/`）。被否，理由与
[ADR 0003](./0003-per-program-app-modules.md) 相同：九节骨架与不变量校验（抓帧校验、
前台判定、目标顶层判定、`state.json` 协议）是**真正共用**的，复制三份等于让不变量有三个
实现，任何一个修 bug 都要改三处 —— 这是与「归属清晰」相反的静默风险。

**把链条数据化到外部配置**（YAML / JSON）。被否：`NODES` 本身就是配置，只是恰好用 Python
字面量写，能带注释与 `why` 文案；换外部格式要引入解析与校验，GUI 又要多一套读取器。
形状已经足够简单（六个字段的列表），不值得为它换语言。

## 后果

**正面**：

- 加第 N 个程序 = 加一条 `Program`（`programs.py`）+ `orchestrator/apps/<key>/__init__.py`
  + `orchestrator/apps/<key>/nodes/__init__.py`（+ 需要的专属节点文件）；
  **不用改 `main.py` / `context.py` / GUI 代码**。
- 节点数与编号可以完全不同：某个程序的链条只有三节也不需要引擎让步；
  `--only/--from/--to` 与 `--list` 自动跟着清单走。
- 「这个程序跑哪几节」只有一处可读：`--list` 打出来的就是清单原文（含 ★ 专属参数标记），
  GUI 与引擎读的是同一份磁盘文件。
- 归属规则变得可检查：`shared=True` 的实现必须在 `steps/common/`，`shared=False` 的必须在
  `apps/<key>/nodes/`；清单写错档名时 `chain()` 直接 `ValueError`，不会跑到别的文件。

**负面，且必须承担**：

- **共用节点要在 N 份清单里各写一遍**。漏写一节 = 该程序少跑一节，而且不会报错 ——
  只能靠 `--list` 与清单自检盯住。这是「一处可读」换来的重复。
- **共用层改动仍需三程序回归**（清单见 [ADR 0003](./0003-per-program-app-modules.md)
  「共用层回归清单」）。拆清单只切断了「加程序改引擎」，没有切断共用机制的波及。
- `chain_key` 只能证明「这份文件属于这个程序」，不能证明「这个程序该有这一节」；
  后者由清单决定，清单写错就是清单写错。
- GUI 与 `main.py` 仍然各读一次清单（GUI 用 `ast`，不能 import 业务模块）：
  是**同一份磁盘文件**，但读取器有两套，清单格式一变要同步两处。

## 验收（本阶段实测）

| 检查 | 结果 |
| --- | --- |
| `python -m compileall -q orchestrator` | exit 0 |
| `python -m pyflakes orchestrator` | **0 个 undefined name** |
| 每个节点模组 import | 都有 `body` / `extra_args` |
| 每个节点模组 `-h` | 全部可解析（共用节点与专属节点各带自己的参数） |
| 程序-节点错配（`--target ww` 跑 `apps/zmd/nodes/step5_wait_ready`） | `[!!]` + rc=2，`state.json` 未写 |
| `python -X utf8 -m orchestrator.steps.main --list` | 按 zmd / ww / nte 逐份打印，节点数与清单一致 |
| `--list --target ww`、`--only 99`、`--only 3` | 单程序清单；不在该程序清单中的编号被拒绝 |
| **第 4 个程序即插即用验收**（临时建 `demo`：4 节、编号 `1/7/42/9`，`42` 是专属节点） | `--list` 打印 4 节；`--only 1`（共用）与 `--only 42`（专属、任意编号）均 rc=0；`--only 5` 被拒并报出 `['1','7','42','9']`；既有三程序不受影响；**引擎代码 0 改动**，验收后临时程序与 `programs.py` 均已还原 |
| GUI 清单读取（`probe/_probe_gui2_selftest.py`、`probe/_probe_gui2_drift.py`） | 62 条 `[OK]`、RC=0；漂移探针改清单后报 2 处、加未登记文件报 1 处，还原后 0 处 |
