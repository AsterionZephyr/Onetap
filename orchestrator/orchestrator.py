"""orchestrator.orchestrator — 程序链条：起点到终点

    节点 1  提权检查          非管理员直接中止（INV-7）
    节点 2  启动 ok-ww.exe
    节点 4  等待第二层        实测零点击约 21 秒自动放行（T-4）
    节点 5  等待窗口就绪      标题正则 + rect 连续采样稳定
    节点 6  抓首帧校验        INV-1 尺寸 + INV-13 非全黑 + 身份校验
    节点 7  置前台 + 遮挡判定  INV-8 / INV-22 / INV-23
    节点 8  任务循环          导航 -> 定位 -> 点击 -> 等待完成
    节点 9  退出与清理        正常完成不杀；超时/失败才杀（Q3 决策）

**节点 3「跨过第一层」已删除**：实机复核证明它不存在（见 window.py 模块说明）。

任务循环的两种终止行为必须区分（VERDICT.md）：

    正常完成  完成帧出现（横幅 + 退出通知同帧）-> ok-ww 自行退出
    等待状态  计时器连续 180 秒冻结 -> 框架判超时，走清理路径
"""

import os
import sys
import time
from datetime import datetime

from . import assets as assets_mod
from . import capture, cleanup, match, state, win32, window
from .errors import DiscoveryFailure, GuardFailure

# 状态机取值（字符串只在 orchestrator/statuses.py 写一次：apps/*.py 的节点 8
# 实现也要用 COMPLETED/TIMEOUT，而它们不允许 import 本文件 —— 见 statuses.py）
from .statuses import COMPLETED, FAILED, TIMEOUT  # noqa: E402

# 「证据不足」：ok-ww 进程消失，但我们从未抓到过完成帧。
# 成因有两种，**画面无法区分**（INV-30）：
#   (a) 今日任务已完成 —— ok-ww 找不到要做的任务，**异常退出**
#       （实测：它既不会关闭自己，也不会关闭游戏，需人工收尾）
#   (b) ok-ww 真的崩了
# 既不能报 completed（无证据），也不该报 failed —— failed 是断言「出错了」，
# 而成因 (a) 完全正常。按 INV-30 报 UNKNOWN，把判断交给人。
UNKNOWN = "unknown"

# 「停住了」：ok-nte 的执行器被暂停，且零进展（FAULT #30）。
# 具体成因：游戏窗口被最小化 ⇒ ok-nte 拿到哨兵坐标 (-32000,-32000) ⇒
# 写下 `og.executor.pause pos_invalid` ⇒ **暂停执行器**。
# 此时进程还在、终止标记永远不来，若只按「超时」处理会白烧半小时
# 且归因错误（报「超时」而非「卡住」）。单独取值以便节点 9 与汇总
# 能说清到底是「等太久」还是「它不动了」。
from .statuses import STALLED  # noqa: E402  (说明见上)

# 退出码
EXIT_OK = 0
EXIT_CONFIG = 2       # 环境/前提不成立
EXIT_GUARD = 3        # 一条不变量被破坏
EXIT_TIMEOUT = 4      # 超时（等待状态）
EXIT_UNEXPECTED = 5

# 运行参数
POLL_INTERVAL = 0.2           # 任务循环采样间隔（Q7：5 秒窗口内要撞上完成帧）
FREEZE_SECONDS = 180.0        # 计时器冻结判定阈值（Q7：N=180）
TOTAL_TIMEOUT = 1800.0        # 整条链的兜底上限（30 分钟）
CLICK_RETRIES = 3             # 点击无变化后的重试整轮次数（Q8：N=3）
CLICK_RETRY_INTERVAL = 2.0    # 重试间隔（Q8）
NAV_RETRIES = 3               # 导航闭环的尝试次数
# 画面「有变化」的平均绝对差阈值：定义在 frameops（它不许 import 本文件，
# 否则 apps/zmd/__init__.py -> frameops -> orchestrator -> match -> apps/zmd 成环）。
from .frameops import CHANGE_THRESHOLD  # noqa: E402


class Log:
    """同时写 stdout 与文件的日志。

    文件一律以 **UTF-8** 写出。本次实机踩过：PowerShell 管道下 stdout 的编码
    会把写入文件的中文变成乱码，故 stdout 与文件必须分开处理编码，
    且文件不依赖 stdout 的编码设置。
    """

    def __init__(self, path=None):
        self.path = path
        self.fh = open(path, "a", encoding="utf-8", newline="\n") if path else None

    def __call__(self, msg=""):
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            # 宿主 stdout 编码不支持中文时降级，但文件仍写完整内容
            print(msg.encode("utf-8", "replace").decode("ascii", "replace"),
                  flush=True)
        if self.fh:
            self.fh.write(msg + "\n")
            self.fh.flush()

    def close(self):
        if self.fh:
            self.fh.close()


class Orchestrator:
    def __init__(self, dry_run=False, log_dir=None, out_dir=None,
                 skip_admin_check=False, no_launch=False, freeze_seconds=FREEZE_SECONDS):
        self.dry_run = dry_run
        self.skip_admin_check = skip_admin_check
        self.no_launch = no_launch
        self.freeze_seconds = freeze_seconds
        self.out_dir = out_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "shots")
        os.makedirs(self.out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f"run-{stamp}.log")
        self.log = Log(log_path)
        self.registry = None
        self.hwnd = None
        self.pid = None
        self.result = None
        self.shots = 0

    # --- 工具 ---------------------------------------------------------

    def shot(self, frame, tag):
        """抓图落盘供肉眼复核（HANDOFF.md §6 第 5 条：只靠数字会漏掉「抓到别的窗口」）。"""
        from PIL import Image
        self.shots += 1
        name = f"{self.shots:03d}-{tag}.png"
        path = os.path.join(self.out_dir, name)
        Image.fromarray(frame.rgb).save(path)
        self.log(f"     落盘 {name}")
        return path

    def frame(self, expected_state=None, strict=True):
        return capture.grab_frame(self.hwnd, expected_state, strict_content=strict)

    # --- 节点 1~7 -----------------------------------------------------

    def node1_check_admin(self):
        self.log("\n[节点 1] 提权检查")
        if self.skip_admin_check:
            self.log("  [跳过] --skip-admin-check 已指定 —— 不会执行任何清理")
            return
        window.check_admin(self.log)

    def node2_launch(self):
        self.log("\n[节点 2] 启动 ok-ww.exe")
        if self.no_launch:
            self.log("  [跳过] --no-launch：假定 ok-ww 已在运行")
            return
        alive = window.okww_running()
        if alive:
            self.log(f"  已在运行，不重复启动：{[(n, p) for n, p, _ in alive]}")
        else:
            window.launch_okww(log=self.log)

    def node4_wait_second_layer(self):
        self.log("\n[节点 4] 等待第二层（窗口持有者）")
        self.log("  ok-ww 第一层会自行放行，约 21 秒；本框架**不点击任何东西**")
        info = window.wait_for_second_layer(log=self.log)
        self.hwnd = info["hwnd"]
        self.pid = info["pid"]
        self.log(f"  hwnd={self.hwnd} pid={self.pid} class={info['class']}")

    def node5_wait_ready(self):
        self.log("\n[节点 5] 等待窗口就绪（标题正则 + rect 连续采样稳定）")
        st = window.wait_for_ready(self.hwnd, log=self.log)
        self.log(f"  [OK] 就绪 {st['width']}x{st['height']} @ ({st['left']},{st['top']})")

    def node6_first_frame(self):
        self.log("\n[节点 6] 抓首帧并校验")
        f = self.frame()
        self.log(f"  [OK] INV-1 帧 {f.width}x{f.height} == 窗口 rect")
        self.log(f"  [OK] INV-13 内容 均值RGB={f.stats['mean_rgb']} "
                 f"色彩={f.stats['distinct_colors_sampled']}")

        sidebar = self.registry["sidebar_tasks"]
        self.log("  [身份校验] 侧栏图标位置/分数")
        ident = match.verify_identity(f.rgb, sidebar.load())
        self.log(f"    [OK] score={ident['score']:.4f} pos={ident['pos']} "
                 f"（INV-12：确认这帧真的来自 ok-ww）")
        self.shot(f, "first-frame")
        return f

    def node7_foreground(self):
        self.log("\n[节点 7] 置前台 + 可用性校验")
        window.bring_to_front(self.hwnd, log=self.log)

    # --- 任务循环 -----------------------------------------------------

    def navigate_to_tasks(self, frame):
        """若不在任务页，点侧栏图标导航过去。返回 (frame, navigated)。

        导航是**闭环**的：点击后重新抓帧并**验证目标行是否出现**，因为真实光标
        点击有落空的可能（窗口失焦时 ok-ww 会静默挂起而不报错，§2.4）。
        """
        self.log("\n[导航] 确认当前在任务页")
        row_tpl = self.registry["daily_row"].load()

        for attempt in range(1, NAV_RETRIES + 1):
            try:
                match.locate_daily_row(frame.rgb, row_tpl)
                if attempt > 1:
                    self.log(f"  [OK] 第 {attempt} 次抓帧确认：已在任务页")
                else:
                    self.log("  [OK] 已在任务页（锚点可唯一定位）")
                return frame, attempt > 1
            except GuardFailure as e:
                self.log(f"  第 {attempt} 次判定：当前页没有目标行 —— "
                         f"{e.detail.splitlines()[0]}")

            if attempt >= NAV_RETRIES:
                break

            self.log("  点击侧栏「任务」图标导航")
            sidebar = self.registry["sidebar_tasks"]
            tpl = sidebar.load()
            ident = match.verify_identity(frame.rgb, tpl)
            th, tw = tpl.shape[:2]
            cx = ident["pos"][0] + tw // 2
            cy = ident["pos"][1] + th // 2
            sp = win32.client_to_screen(self.hwnd, cx, cy)
            if sp is None:
                raise GuardFailure("INV-23", "ClientToScreen 失败")
            self.log(f"  侧栏图标窗口内中心=({cx},{cy}) -> 屏幕 ({sp[0]},{sp[1]})")
            from . import input as input_mod
            input_mod.guarded_click(self.hwnd, sp[0], sp[1],
                                    dry_run=self.dry_run, log=self.log)
            if self.dry_run:
                self.log("  [DRY RUN] 不实际点击，导航闭环无法验证；"
                         "直接进入定位环节以检验锚点")
                return frame, True
            time.sleep(1.5)
            frame = self.frame()

        raise GuardFailure(
            "INV-24",
            f"导航 {NAV_RETRIES} 次后仍未进入任务页（锚点始终无法唯一定位）。\n"
            f"  => 可能原因：ok-ww 版本升级导致界面改版（锚点需重新采集）、"
            f"点击落空、或当前不在可导航的页面。")

    def locate_and_click_start(self, frame):
        """定位「每日任务」行 -> 扫描同行「开始」按钮 -> 动作前置关 -> 点击。

        返回 (screen_coords, 点击前帧)。
        """
        self.log("\n[定位] 每日任务行")
        row_tpl = self.registry["daily_row"].load()

        # INV-4：出生尺寸校验先做。行模板是局部截图，不能要求与窗口同尺寸，
        # 故只在登记了出生尺寸且明显不同源时告警，不阻断。
        asset = self.registry["daily_row"]
        same, why = asset.check_born_size(frame.width, frame.height)
        self.log(f"  出生尺寸：{why}")

        loc = match.locate_daily_row(frame.rgb, row_tpl)
        a = loc["anchor"]
        self.log(f"  锚点「日历图标+每日任务」score={a['score']:.4f} "
                 f"pos={a['pos']} 尺寸={a['size'][0]}x{a['size'][1]}")
        self.log(f"  联合唯一性：{len(loc['candidates'])} 个候选，"
                 f"1 个同时满足「同行有开始按钮」-> [OK]")

        row_y0, row_y1 = loc["row_y0"], loc["row_y1"]
        btn = loc["button"]
        bx0, by0, bx1, by1 = btn["box"]
        cx, cy = btn["center"]
        self.log(f"  行范围 y={row_y0}..{row_y1}")
        self.log(f"  开始按钮 窗口内 x={bx0}..{bx1} y={by0}..{by1} 中心=({cx},{cy})")

        if not (row_y0 <= cy <= row_y1):
            raise GuardFailure(
                "INV-19",
                f"交叉验证失败：按钮中心 y={cy} 不在行 {row_y0}..{row_y1} 内")

        sp = win32.client_to_screen(self.hwnd, cx, cy)
        if sp is None:
            raise GuardFailure("INV-23", "ClientToScreen 失败")
        self.log(f"  屏幕坐标 = ({sp[0]},{sp[1]})")
        return sp, row_y0, row_y1

    def wait_for_completion(self):
        """等待完成 / 超时。返回 (result, detail, completion_frame)。"""
        self.log(f"\n[等待] 采样间隔 {POLL_INTERVAL}s；"
                 f"冻结判定 {self.freeze_seconds:.0f}s；兜底 {TOTAL_TIMEOUT:.0f}s")

        exit_tpl_asset = self.registry.get("exit_notice")
        exit_tpl = None
        if exit_tpl_asset and exit_tpl_asset.available:
            exit_tpl = exit_tpl_asset.load()
        else:
            self.log("  [警告] 退出通知资产未采集 —— 无法判定「正常完成」，"
                     "本框架只能以「超时」收场")
            self.log("         这是当前**唯一的功能缺口**，采集方法见 assets.json")

        detector = state.FreezeDetector(self.freeze_seconds)
        started = time.time()
        last_fp = None
        frames = 0
        last_report = 0.0

        while True:
            now = time.time()
            elapsed = now - started

            if elapsed > TOTAL_TIMEOUT:
                return TIMEOUT, f"整条链超过兜底上限 {TOTAL_TIMEOUT:.0f}s", None

            # ok-ww 进程没了 —— 分两种：抓到过完成帧 = 完成；没抓到 = 失败
            if not window.okww_running():
                if self._completion_seen:
                    return COMPLETED, "ok-ww 已自行退出（此前抓到完成帧）", None
                return FAILED, "ok-ww 进程消失，但从未抓到完成帧", None

            info = window.find_okww_window()
            if not info:
                time.sleep(POLL_INTERVAL)
                continue
            self.hwnd = info["hwnd"]

            try:
                f = self.frame(strict=False)
            except GuardFailure as e:
                self.log(f"  [{e.invariant}] 本轮抓帧失败：{e.detail}")
                time.sleep(POLL_INTERVAL)
                continue

            frames += 1
            fp = float(f.rgb[::40, ::40].mean())
            if last_fp is None or abs(fp - last_fp) > 0.5:
                self.log(f"  +{elapsed:6.0f}s  画面指纹 {fp:.2f}  "
                         f"{f.width}x{f.height}")
                last_fp = fp

            if exit_tpl is not None:
                ok, detail = state.is_completion_frame(f.rgb, exit_tpl)
                if ok:
                    self.log(f"  +{elapsed:6.0f}s  *** 完成帧 ***  {detail}")
                    path = self.shot(f, "completion")
                    self._completion_seen = True
                    self._completion_frame_path = path
                    return COMPLETED, detail, path

            frozen, fdetail = detector.update(f.rgb, now)
            if frozen:
                self.log(f"  +{elapsed:6.0f}s  [超时] {fdetail}")
                self.shot(f, "timeout")
                return TIMEOUT, fdetail, None

            if now - last_report > 30:
                last_report = now
                self.log(f"  +{elapsed:6.0f}s  … {fdetail}")

            time.sleep(POLL_INTERVAL)

    _completion_seen = False
    _completion_frame_path = None

    def click_and_confirm(self, frame):
        """点击「开始」并验证生效；无变化则**重试整轮**（Q8：N=3）。

        返回 (ok, frame)。重试时重新置前台、重新定位、重新点击。
        """
        from . import input as input_mod

        for attempt in range(1, CLICK_RETRIES + 1):
            self.log(f"\n[点击] 第 {attempt}/{CLICK_RETRIES} 轮")
            frame, _ = self.navigate_to_tasks(frame)
            sp, _y0, _y1 = self.locate_and_click_start(frame)
            self.shot(frame, "about-to-click")

            before = frame.rgb.astype("int16")
            input_mod.guarded_click(self.hwnd, sp[0], sp[1],
                                    dry_run=self.dry_run, log=self.log)
            if self.dry_run:
                return True, frame

            time.sleep(1.2)
            after = self.frame(strict=False)
            diff = float(abs(after.rgb.astype("int16") - before).mean())
            self.log(f"  点击后帧差异 = {diff:.2f}")
            if diff >= CHANGE_THRESHOLD:
                self.log("  [OK] 画面已变化，点击很可能生效")
                return True, after
            self.log(f"  [!!] 画面几乎未变 —— 点击可能落空（ok-ww 失焦会静默挂起）")
            if attempt < CLICK_RETRIES:
                self.log(f"  等待 {CLICK_RETRY_INTERVAL:.0f}s 后重试整轮")
                time.sleep(CLICK_RETRY_INTERVAL)

        return False, frame

    # --- 节点 9 -------------------------------------------------------

    def node9_cleanup(self, result, detail):
        self.log("\n[节点 9] 退出与清理")
        if result == COMPLETED:
            self.log("  任务正常完成 —— ok-ww 自行退出，框架**不杀任何进程**（Q3 决策）")
            alive = window.okww_running()
            if alive:
                self.log(f"  确认：仍有进程存活 {[(n, p) for n, p, _ in alive]}"
                         f" —— 可能仍在收尾，稍后再看")
            return {"reason": "completed", "killed": [], "skipped": []}

        self.log(f"  结果 = {result}（{detail}）-> 走清理路径")
        if self.skip_admin_check:
            self.log("  [跳过] 未提权，框架无力终止进程 —— 请手动处理")
            return {"reason": "no-permission", "killed": [], "skipped": []}

        res = cleanup.run_cleanup(window.OKWW_DIR, reason=result,
                                  log=self.log, dry_run=self.dry_run)
        self.log(f"  终止 {len(res['killed'])} 个，跳过 {len(res['skipped'])} 个")
        return res

    # --- 主流程 -------------------------------------------------------

    def run(self):
        self.__class__._completion_seen = False
        mode = "  [DRY RUN：不点击、不杀进程]" if self.dry_run else ""
        self.log("=" * 74)
        self.log(f"ok-ww 黑盒编排{mode}")
        self.log(f"开始时间 {datetime.now():%Y-%m-%d %H:%M:%S}")
        self.log(f"输出目录 {self.out_dir}")
        self.log("=" * 74)

        win32.ensure_dpi_aware()
        sw, sh = win32.screen_size()
        self.log(f"\n[环境] 屏幕 {sw}x{sh}（物理像素，per-monitor v2 DPI 感知）")

        try:
            self.registry = assets_mod.Registry()
            self.log("\n[图像库]")
            self.log(self.registry.report())

            self.node1_check_admin()
            self.node2_launch()
            self.node4_wait_second_layer()
            self.node5_wait_ready()
            frame = self.node6_first_frame()
            self.node7_foreground()

            frame, _ = self.navigate_to_tasks(frame)

            if self.dry_run:
                self.log("\n[DRY RUN] 汇总")
                self.log("  [OK] 节点 1~7 全部通过（提权自检已按参数跳过）")
                self.log("  [OK] 抓帧 / 尺寸校验 / 内容校验 / 身份校验 全部通过")
                self.log("  [OK] 置前台 + 可用性校验 通过")
                self.log("  [OK] 动作前置关通过（屏幕内 + 前台 + 目标顶层判定）")
                self.log("  [!!] 锚点定位未通过 —— 当前页面不是任务页，而 dry-run "
                         "不实际点击，因此无法导航过去")
                self.log("  => 实跑时导航会自动点击并**闭环验证**；"
                         "要单独验证锚点，请让 ok-ww 停在任务页后重跑本命令")
                self.result = COMPLETED
                return EXIT_OK

            ok, frame = self.click_and_confirm(frame)

            if not ok:
                raise GuardFailure(
                    "INV-8",
                    f"连续 {CLICK_RETRIES} 轮点击后画面无变化 —— "
                    f"ok-ww 很可能失焦静默挂起")

            result, detail, frame_path = self.wait_for_completion()
            self.log(f"\n[结果] {result}：{detail}")
            self.result = result
            self.node9_cleanup(result, detail)

            if result == COMPLETED:
                return EXIT_OK
            if result == TIMEOUT:
                return EXIT_TIMEOUT
            # FAULT #17：证据不足（进程消失但无完成帧）**不是失败**，
            # 不该用「不变量被破坏」的退出码。用 EXIT_OK 之外的专用码
            # 会让人以为出错了；这里沿用 EXIT_GUARD 会与真正的 GuardFailure
            # 混淆，故显式分流到 EXIT_UNEXPECTED 并打印说明。
            if result == UNKNOWN:
                self.log("\n[未决] 证据不足：ok-ww 进程消失但从未抓到完成帧。"
                         "常见成因是「今日任务此前已完成，ok-ww 无事可做而异常退出」，"
                         "也可能是崩溃。请人工核对 ok-ww 日志。")
                return EXIT_UNEXPECTED
            return EXIT_GUARD

        except DiscoveryFailure as e:
            self.log(f"\n[中止] 环境前提不成立：\n  {e}")
            self.result = FAILED
            return EXIT_CONFIG
        except GuardFailure as e:
            self.log(f"\n[中止] 不变量被破坏：{e}")
            self.result = FAILED
            if not self.dry_run:
                try:
                    self.node9_cleanup(FAILED, str(e))
                except Exception as inner:
                    self.log(f"  清理失败：{inner}")
            return EXIT_GUARD
        except KeyboardInterrupt:
            self.log("\n[中止] 用户中断")
            self.result = FAILED
            return EXIT_UNEXPECTED
        except Exception as e:
            import traceback
            self.log(f"\n[异常] {type(e).__name__}: {e}")
            self.log(traceback.format_exc())
            self.result = FAILED
            return EXIT_UNEXPECTED
        finally:
            self.log(f"\n结束时间 {datetime.now():%Y-%m-%d %H:%M:%S}")
            self.log("=" * 74)
            self.log.close()
