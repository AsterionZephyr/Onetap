# probe/ — 证据脚本索引

**这一层不是产品代码。** 正式实现在 [`orchestrator/`](../orchestrator/)；这里放的是**一次性探测脚本**与**可反复跑的自检**，作用是「当时凭什么这么写」的证据。改产品代码不需要动这里，但**改共用层后应当跑哪些自检**看 [`docs/adr/0003`](../docs/adr/0003-per-program-app-modules.md) 的回归清单和下面「回归自检」那一组。

## 跑法

```powershell
cd E:\TOOLS\ScriptsGames\Onetap
python -X utf8 probe/_check_workspace.py          # 工作区门禁：exit 0 才算合格
python -X utf8 probe/_probe_gui2_selftest.py      # GUI 两页无头自检（62 条）
python -X utf8 probe/zmd_wait_selfcheck.py        # 离线自检，不碰目标程序
```

- 一律在**仓库根**执行（脚本自己按 `Path(__file__).resolve().parent.parent` 推仓库根，不依赖当前目录）。
- **离线脚本**（描述里写了「离线」「不碰真实窗口 / 日志」「只读」）随时可跑，不需要管理员。
- **会开窗 / 会点鼠标 / 会真起目标程序**的脚本需要管理员会话，且可能占用屏幕几分钟（描述里写了）。
- 约定：自检类 `exit 0` = 通过，非 0 或打印 FAIL 即违约。

## 命名约定

| 名字 | 含义 |
| --- | --- |
| `_probe_*.py` | 一次性探针：某次故障 / 某次选型的取证脚本，多数不需要再跑 |
| `*_selfcheck.py` / `_probe_gui2_selftest.py` | 可反复跑的回归自检，改共用层后按 [`docs/adr/0003`](../docs/adr/0003-per-program-app-modules.md) 清单跑 |
| 无下划线的（`capture.py`、`cleanup.py`、`ww_verdict.py`、`nte_verdict.py`、`pngout.py`、`template_probe.py`、`ww_action.py`、`nte_main.py`、`refresh_assets.py`） | 正式实现的前身，保留作证据；产品代码用的是 `orchestrator/` 里的同名模块 |

## 图像资产

| 文件 | 用途 |
| --- | --- |
| `obs-000.png`、`okww-now.png`、`running-000.png` | 历史抓帧（尺寸 / 分数被 [`docs/FAULT-LOG.md`](../docs/FAULT-LOG.md) 的表格引用；`running-000.png` 还是 [`docs/RUNBOOK.md`](../docs/RUNBOOK.md) 里节点 6 离线复验的 `--adopt-frame` 输入） |
| `fixtures/zmd_full.png`、`fixtures/zmd_run_ok.txt`、`fixtures/zmd_update_done.png`、`fixtures/zmd_update_downloading.png` | MaaEnd 自检的固定夹具（`zmd_verdict_selfcheck.py` / `zmd_update_selfcheck.py` / `zmd_wait_selfcheck.py` 直接读） |

## 索引

「引用数」= 仓库里其它文件提到该文件名的次数（0 = 只有本索引提到它，不代表没用，只代表没人再引）。

### 门禁

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `_check_workspace.py` | **工作区门禁**（8 条，exit≠0 即违约）：C1~C4 目录契约（根目录文件、docs/ 只放文档、README 目录表、无残留）+ C5~C7 文档一致性（相对链接、「共 N 条」声明、INV/FAULT/规则编号引用）+ C8 日志保留（`logs/runs/` 超十轮只提示，见 RUNBOOK §11） | 339 | 0 |

### 回归自检（守已修故障：FAULT #n / INV-n）

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `_probe_verdict.py` | orchestrator.verdict 的日志判据回归（24 项断言，含真实假阳性场景） | 193 | 3 |
| `_probe_ww_verdict.py` | ok-ww 用日志判据判终态回归（19 项，FAULT #15） | 171 | 5 |
| `_probe_nte_verdict.py` | ok-nte 判据回归（16 项，FAULT #18） | 132 | 3 |
| `_probe_win32_admin.py` | orchestrator.win32 的句柄原型与 is_admin 回归（is_admin 曾恒返回 False） | 91 | 3 |
| `_probe_menu_glyph.py` | 程序化 ☰ 检测的正负样本（5 正 + 5 负 + 6 合成负 ⇒ 16/16） | 124 | 3 |
| `_probe_nte_locate.py` | ok-nte 定位器回归（复选框 / 开始按钮 / 页面定位，13/13） | 131 | 1 |
| `_probe_nte_settle.py` | ok-nte 见到终止标记后的「收尾宽限」（15 项，FAULT #27） | 221 | 2 |
| `_probe_nte_game_settle.py` | 节点 8 开工前必须等 ok-nte 把游戏拉起并稳定（FAULT #28） | 183 | 0 |
| `_probe_frame_changed.py` | frame_changed / 完成帧检测回归（11/11，FAULT #23 / #24） | 155 | 2 |
| `_probe_logwindow_arming.py` | LogWindow 必须在**点击之前**武装（9/9，六个场景，FAULT #25） | 128 | 4 |
| `_probe_executor_pause.py` | 执行器暂停诊断（pos_invalid 哨兵坐标，FAULT #30） | 259 | 5 |
| `_probe_foreground.py` | 抢前台的三种手段：静态 12 项 + live 实测（FAULT #29） | 141 | 3 |
| `_probe_foreground_click.py` | 抢前台的最后一手：真实点击窗口体夺取激活（FAULT #35），静态 AST + 打桩，不依赖 live | 253 | 1 |
| `_probe_force_close_all.py` | 跨程序清理 force_close(all_programs=True) 回归（FAULT #32：None 不等于「全部」） | 115 | 1 |
| `_probe_unknown_cleanup.py` | ok-nte 侧 UNKNOWN 分支的自动收尾回归（纯静态 + 只读） | 145 | 1 |
| `_probe_ww_unknown_cleanup.py` | ok-ww UNKNOWN + 游戏残留的自动收尾回归（三层，含 --live 真起游戏） | 149 | 1 |
| `_probe_state_race.py` | state.json 原子替换 vs 读轮询的撞车率（FAULT #37：裸 os.replace 实测 7.8%，--verify-fix 必须 0 失败） | 257 | 3 |
| `_probe_stalled_live.py` | FAULT #30 的 STALLED 分支：真起 ok-ww 制造卡死，一路跑到收尾判 failed | 315 | 2 |
| `_probe_watchdog.py` | watchdog 超时收尾的端到端验证（不碰真实目标程序） | 176 | 0 |
| `_probe_run_timeout.py` | 整轮时间上限 RUN_TIMEOUT 的超时收尾（用户裁定：半小时到点关窗口关游戏） | 277 | 0 |
| `_probe_gui2_selftest.py` | 两页 GUI 的无头自检（62 条断言，RC=0） | 386 | 5 |
| `_probe_gui2_drift.py` | 清单漂移守卫真的会报警（改清单报 2 处、加未登记文件报 1 处、还原后 0 处） | 103 | 4 |
| `_probe_gui2_runner.py` | gui.runner 真能驱动 steps/main.py（18 项，真起进程真终止） | 216 | 2 |
| `_probe_gui_target_wire.py` | GUI 目标选择器真的把 --target 送出去了（调真实 on_run、stub Runner 看 argv） | 235 | 4 |
| `_probe_gui_both_live.py` | 用真实 App 驱动 GUI 跑一次多目标串联（--dry-run 冒烟 2.5s，全程约 12 分钟） | 250 | 3 |
| `activate_selfcheck.py` | 置前台「真实点击夺取激活」的离线自检 | 151 | 3 |
| `apps_shims_selfcheck.py` | 共用层 __getattr__ 垫片仍指向 apps/<key> 的真身（含 programs / targets 的 self_check） | 32 | 2 |
| `zmd_click_selfcheck.py` | zmd_click_and_confirm 的三级证据（离线；回归 frame_changed 返回 tuple 那个静默 bug） | 91 | 4 |
| `zmd_locate_selfcheck.py` | MaaEnd 绿色「开始任务」按钮定位器（离线，只用 Pillow + numpy） | 224 | 4 |
| `zmd_update_selfcheck.py` | MaaEnd 自我更新闸门（apps/zmd 第 3 段，离线） | 287 | 1 |
| `zmd_verdict_selfcheck.py` | MaaEnd 运行判据——用真实历史切片回放 | 324 | 4 |
| `zmd_wait_selfcheck.py` | zmd_wait_completion 的「关游戏后升级证据」分支（离线） | 72 | 4 |

### MaaEnd（`--target zmd`）

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `zmd_preflight.py` | MaaEnd 冷启动前的只读体检（要求 app 尚未运行） | 63 | 2 |
| `zmd_windows.py` | 列出 MaaEnd 相关进程与窗口（只读） | 51 | 0 |

### ok-nte（`--target nte`）

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `nte_main.py` | ok-nte 主界面适配勘察 + 模板定位 | 180 | 8 |
| `nte_verdict.py` | ok-nte 终态判据（Q2 交付物；正式版见 orchestrator/verdict.py） | 353 | 9 |
| `_probe_nte_assets.py` | 既有图像资产在 v1.4.14 真实帧上是否仍有效（INV-35） | 92 | 1 |
| `_probe_nte_band.py` | 侧栏横向扫描带的逐行亮像素剖面（find_sidebar_item 只找到 7/13 项时用） | 49 | 0 |
| `_probe_nte_carousel.py` | 内容区那条全宽图片轮播是瞬态还是常驻 | 68 | 0 |
| `_probe_nte_geom.py` | 任务页行几何与「开始」按钮位置（v1.4.14） | 83 | 0 |
| `_probe_nte_grab.py` | 抓一帧已置前台的干净 ok-nte 帧落盘 | 43 | 0 |
| `_probe_nte_menu_asset.py` | 实时帧里的 ☰ 与既有模板逐像素对照 | 67 | 1 |
| `_probe_nte_nav.py` | 顶部导航组的选中态（青色高亮）与结构 | 70 | 0 |
| `_probe_nte_rowcrop.py` | 任务页每行逐行裁图落盘，供人眼核对 | 76 | 0 |
| `_probe_nte_rows.py` | 任务页的行结构（行间距、行内元素），用于设计行定位策略 | 72 | 0 |
| `_probe_nte_sidebar.py` | ok-nte 侧栏结构 | 54 | 0 |
| `_probe_nte_state.py` | 抓帧前后确认「抓到的是不是 ok-nte」，并揪出遮挡者 | 70 | 0 |

### ok-ww（`--target ww`）

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `ww_verdict.py` | ok-ww 终态判据（Q1 交付物，基于日志；正式版见 orchestrator/verdict.py） | 261 | 6 |
| `ww_action.py` | ok-ww 动作元素定位（行结构扫描找「开始」） | 115 | 2 |
| `template_probe.py` | 模板与当前窗口的几何关系测绘（只读，不点击） | 171 | 4 |
| `refresh_assets.py` | 按当前程序版本重采图像资产 | 275 | 1 |
| `_probe_ww_sessions.py` | 把 ok-ww 日志按会话切开列结局（找「已做完而异常退出」的真实样本） | 67 | 2 |
| `_probe_sidebar.py` | 量取 ok-ww 侧栏「任务」项的位置（不依赖截图模板的定位依据） | 101 | 0 |
| `_probe_sidebar_item.py` | find_sidebar_item 从真实抓帧定位侧栏「任务」项 | 81 | 1 |
| `_probe_menu_geom.py` | 真 ☰ 与干扰项的几何分布，为阈值定数（不要凭感觉设常数） | 138 | 0 |

### GUI / Tk

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `_probe_tk_editor.py` | tkinter 能否写出「行号 + 语法高亮 + 保存 + 撤销」的编辑器（可行性实测） | 284 | 3 |
| `_probe_tk_incremental.py` | 增量高亮能否把编辑器拉回「打字流畅」（相对全量实测提速 195×） | 97 | 3 |
| `_probe_tk_bench.py` | 全量重打高亮的成本随文件规模增长（O(n²) 的证据） | 66 | 0 |
| `_probe_gui_selftest.py` | GUI 骨架的线程 / 队列边界集成自检 | 94 | 0 |
| `_probe_gui_preview.py` | 「帧预览」面板真的能渲染（喂真实图像给 show_frame） | 46 | 0 |
| `_probe_gui_visual.py` | 节点高亮在实际运行中是否可见（不依赖合成点击） | 63 | 0 |
| `_probe_gui2_coords.py` | 打印 GUI 控件的精确屏幕坐标（Tk 自己算，不靠截图估算） | 99 | 0 |
| `_probe_gui2_runonce.py` | on_run 是否真能起子进程（绕开鼠标直接驱动） | 87 | 0 |
| `_probe_gui2_stop.py` | taskkill /T /F 之后进程到底还在不在（os.kill(pid, 0) 会误报） | 76 | 3 |
| `_probe_gui2_tabclick.py` | 真窗口 + 真鼠标：Notebook 页签切换是否可用 | 70 | 0 |
| `_probe_gui2_livetour.py` | 逐节点实机巡游：启动真 GUI 模拟真实操作，记录每步成败 | 206 | 0 |
| `_probe_gui2_visual.py` | 打开真窗口停在一个可截屏的状态（供肉眼复核） | 69 | 2 |
| `_probe_gui2_perf.py` | 高亮性能：全量 vs 增量 | 81 | 1 |
| `_probe_gui2_sec5.py` | 只跑自检的第 5 节，带分步计时定位卡在哪一步 | 52 | 0 |

### 通用（抓帧、进程、早期实现）

| 脚本 | 它证明什么 / 干什么 | 行数 | 引用数 |
| --- | --- | --- | --- |
| `capture.py` | 窗口发现 / 抓帧 / 帧统计 / PNG 落盘的早期实现（正式版在 orchestrator/capture.py） | 212 | 10 |
| `cleanup.py` | 编排层清理策略的早期实现（Q3 交付物；正式版在 orchestrator/cleanup.py） | 301 | 31 |
| `pngout.py` | 纯标准库 PNG 写出（当时的环境没有 Pillow / numpy） | 36 | 1 |
| `targets_preflight.py` | 串联测试前的只读体检：按执行顺序逐程序看「现在能不能跑」 | 123 | 0 |
| `_probe_elev.py` | 检查指定 pid 的完整性级别（提权与否），并对比自己的 | 82 | 0 |
| `_probe_detach.py` | 完全脱离父进程树的启动方式（无人值守长跑的前提） | 128 | 0 |
| `_probe_bg_life.py` | Start-Process 起的独立进程能否脱离 DSH 宿主存活 | 19 | 0 |
| `_probe_first_layer_ownership.py` | 第一层（启动器 shell）的可见性与可清除性（FAULT #34） | 145 | 0 |
| `_probe_flip_diag.py` | 上下翻转的帧里 find_menu_glyph 到底匹配到了什么（诊断 N-1） | 105 | 0 |

## 新增探针的规矩

1. **docstring 第一行写清「它证明什么 / 怎么跑」** —— 本索引就是照这一行生成的，没有它就只能靠猜。
2. **优先离线**：能用固定夹具证明的，不要真起目标程序；必须 live 的在 docstring 里写明需要什么前置。
3. **别把抓帧产物留在仓库**：临时帧写 `logs/`（已 gitignore）；确需入库的夹具放 `probe/fixtures/`，体积要小。
4. 一次性脚本用完可以删 —— 只要结论已经写进 `docs/`；git 历史里查得到。

## 整理记录（2026-10-23）

- 22 个原本住在 `docs/` 的探针搬到这里：与 `docs/` **同深度**，所以脚本里 `parent.parent` 推仓库根的写法一个都不用改。
- 删掉 19 个零引用、无说明的一次性脚本（其中 `_probe_gui2_stepnote.py` 连语法都不通过）；需要时从 git 历史取回。
- 新增 `_check_workspace.py`：把「根目录只放三份文件 / `docs/` 只放文档 / README 目录表对得上 / 无垃圾残留」变成 exit≠0 的门禁；回归清单里也加了一条。
- 之后（ADR 0007）又给同一个脚本补了 C5~C7：文档相对链接、「共 N 条」声明与现实条目数、`INV-nn` / `FAULT #nn` / `硬性规则 n` 的引用可解析。反例验证过：故意写坏链接 / 写错条数 / 引用不存在的 INV 都会 FAIL。
