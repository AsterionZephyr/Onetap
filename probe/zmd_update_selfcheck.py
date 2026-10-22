# -*- coding: utf-8 -*-
r"""自检：MaaEnd **自我更新闸门**（apps/zmd/__init__.py 第 3 段）。

只读 + 离线：只用 Pillow + numpy，不抓屏、不点鼠标、不碰目标程序。
两张真实截图（2026-10-19 用户提供，v2.34.0 更新过程）就是判据的来源：

    probe/fixtures/zmd_update_downloading.png  下载中（右上气泡 + 进度条）
    probe/fixtures/zmd_update_done.png         更新完成模态框 + 右下绿色「知道了」

用例：
  [1] 「知道了」正例：done 帧必须定位到 box≈(796,684,872,724) center≈(834,704)
  [2] 「知道了」负例：downloading 帧**不能**定位到任何 ack 形态绿块
  [3] 「知道了」负例：正常帧（zmd_full.png）不能定位到 ack（否则会点开始任务）
  [4] 歧义闸门：把按钮复制一份同尺寸的，必须拒（INV-24 同理）
  [5] 阶段状态机（纯函数 zmd_update_phase）：idle/detecting/downloading/
      installing/finished + 时间基线过滤 + 资源包不算自我更新
  [6] 闸门驱动逻辑：idle 立即放行、detecting 超宽限放行、downloading 超时
      （用 monkeypatch 替掉 probe，不依赖真实日志内容）
  [7] 真实日志：最新应用日志能被 zmd_app_log_path 找到；今天这份里若有
      「检测到刚更新完成」就断言能识别（没有则 SKIP，不假失败）

用法：
    & D:\WORKs\Anaconda\python.exe probe\zmd_update_selfcheck.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from orchestrator import apps

# 本机控制台是 GBK(936)：脚本里有 ±/≥/≈ 之类的符号时，默认 stdout 会在 print
# 阶段抛 UnicodeEncodeError，让自检「假失败」。改用 replace。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

Z = apps.get("zmd")
FIX = ROOT / "probe/fixtures"
DONE = FIX / "zmd_update_done.png"
DL = FIX / "zmd_update_downloading.png"
NORMAL = FIX / "zmd_full.png"
if not NORMAL.exists():
    NORMAL = ROOT / "logs/probe/zmd_full.png"

# 实测事实（step=4 连通域，done 帧 1184x816）
EXPECT_ACK_BOX = (796, 684, 872, 724)
EXPECT_ACK_CENTER = (834, 704)
TOL = 6
FAILS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}{(' —— ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)
    return cond


def skip(name, why):
    print(f"  [SKIP] {name} —— {why}")


def hr(title):
    print()
    print("=" * 72)
    print(title)


def near(a, b, tol=TOL):
    return all(abs(int(x) - int(y)) <= tol for x, y in zip(a, b))


def load(p):
    return np.asarray(Image.open(p).convert("RGB"))


def main():
    hr("[0] 环境 / 契约")
    for p in (DONE, DL, NORMAL):
        print(f"  {'found  ' if p.exists() else 'MISSING'} {p.relative_to(ROOT)}")
    if not (DONE.exists() and DL.exists() and NORMAL.exists()):
        print("  [SKIP] 缺少 fixture，无法自检")
        return 2
    done = load(DONE)
    dl = load(DL)
    normal = load(NORMAL)
    print(f"  done={done.shape[1]}x{done.shape[0]}  "
          f"downloading={dl.shape[1]}x{dl.shape[0]}  "
          f"normal={normal.shape[1]}x{normal.shape[0]}")
    check("闸门上限 1800s（实测 300MB 约 7 分钟）",
          Z.ZMD_UPDATE_WAIT_SECONDS == 1800.0, f"{Z.ZMD_UPDATE_WAIT_SECONDS}")
    # 两套判据必须**真的不同**：ack 更瘦（1.5~3.0 vs 2.0~4.0）且下沿必须高于
    # 底部控制条 —— 否则「开始任务」也会被当 ack（正常帧上就会点错）
    check("ack 宽高比上限 < start 下限（两套判据不重合）",
          Z.ZMD_ACK_WH_MAX < Z.ZMD_WH_MAX and Z.ZMD_ACK_WH_MIN < Z.ZMD_WH_MIN,
          f"ack=[{Z.ZMD_ACK_WH_MIN},{Z.ZMD_ACK_WH_MAX}] "
          f"start=[{Z.ZMD_WH_MIN},{Z.ZMD_WH_MAX}]")
    check("ack 下沿闸门 < 1.0（排除底部控制条里的开始任务）",
          Z.ZMD_ACK_Y1_FRAC < 1.0, f"{Z.ZMD_ACK_Y1_FRAC}")

    # ---------------------------------------------------------------- 1)
    hr("[1] 「知道了」正例：更新完成帧")
    t0 = time.perf_counter()
    info = Z.zmd_locate_ack(done)
    dt = (time.perf_counter() - t0) * 1000
    btn = info["button"]
    if not check("必须定位到一个 ack 按钮", btn is not None,
                 f"reason={info['reason']}"):
        return 1
    print(f"  box={btn['box']} center={btn['center']} area={btn['area']} "
          f"白占比={btn['white_frac']:.3f}（{dt:.0f} ms）")
    check("box 四边在预期 ±6px 内", near(btn["box"], EXPECT_ACK_BOX),
          f"{btn['box']} vs {EXPECT_ACK_BOX}")
    check("center 在预期 ±6px 内", near(btn["center"], EXPECT_ACK_CENTER),
          f"{btn['center']} vs {EXPECT_ACK_CENTER}")
    check("帧尺寸与输入一致", info["frame_size"] == (done.shape[1], done.shape[0]))
    # 被模态遮罩压暗的「开始任务」必须被 y1 闸门挡掉（实测它仍有 132 格绿、
    # 白占比 0.000 —— 两个理由都该拒它）
    print("  被拒连通域（前 4 个）：")
    for box, why in info["rejected"][:4]:
        print(f"    box={box} {why}")

    # ---------------------------------------------------------------- 2)
    hr("[2] 负例：下载中帧（只有进度条/气泡，没有弹窗）")
    info2 = Z.zmd_locate_ack(dl)
    check("不得定位到 ack 按钮", info2["button"] is None,
          f"却给了 {info2['button']['box'] if info2['button'] else None}")
    if info2["button"] is None:
        print(f"  reason={info2['reason']}  候选={len(info2['candidates'])} 个")
    # 同一帧上「开始任务」仍是正常形态 —— 说明下载阶段界面可用
    start = Z.zmd_locate_start(dl)
    print(f"  同帧「开始任务」box={start['button']['box']} "
          f"center={start['button']['center']}（正常形态，界面没被遮罩）")
    check("下载中帧的「开始任务」可正常定位（界面没被遮罩）",
          start["button"]["box"] is not None)

    # ---------------------------------------------------------------- 3)
    hr("[3] 负例：正常帧（底部「开始任务」在，但**没有** ack 形态按钮）")
    info3 = Z.zmd_locate_ack(normal)
    check("不得把「开始任务」当成「知道了」", info3["button"] is None,
          f"却给了 {info3['button']['box'] if info3['button'] else None}")
    if info3["button"] is None:
        print(f"  reason={info3['reason']}")
        for box, why in info3["rejected"][:4]:
            print(f"    box={box} {why}")

    # ---------------------------------------------------------------- 4)
    hr("[4] 歧义闸门：同尺寸按钮出现两个 ⇒ 不点（INV-24 同理）")
    cover = done.copy()
    x0, y0, x1, y1 = EXPECT_ACK_BOX
    patch = done[y0:y1, x0:x1].copy()     # 就是那个「知道了」
    # 再贴一份到右半屏、模态框高度带内（y 450、x 900）—— 长宽比/白占比全一样
    cover[450:450 + (y1 - y0), 900:900 + (x1 - x0)] = patch
    info4 = Z.zmd_locate_ack(cover)
    cands = info4["candidates"]
    print(f"  候选={len(cands)} 个  button={'有' if info4['button'] else '无'}  "
          f"reason={info4['reason']}")
    if len(cands) >= 2:
        check("两个同款候选 ⇒ 拒绝（不赌）", info4["button"] is None,
              f"reason={info4['reason']}")
    else:
        skip("歧义闸门", f"只找到 {len(cands)} 个候选，构造失败")

    # ---------------------------------------------------------------- 5)
    hr("[5] 阶段状态机（纯函数，合成日志文本）")
    TS = "2026-10-19"
    base = Z.zmd_update_baseline(now=__import__("datetime").datetime(2026, 10, 19, 23, 44),
                                 lookback=3600)
    app_fin = f"[{TS}][23:43:20] INFO [App] 检测到刚更新完成: v2.34.0"
    tauri_lines = {
        "detect": f"[{TS}][23:35:25] INFO [mxu_lib::commands::download] "
                  f"找到匹配的 Release: v2.34.0 (tag: v2.34.0)",
        "start": f"[{TS}][23:35:26] INFO [mxu_lib::commands::download] download_file: "
                 f"https://github.com/MaaEnd/MaaEnd/releases/download/v2.34.0/"
                 f"MaaEnd-win-x86_64-v2.34.0.zip -> E:/TOOLS/ScriptsGames/zmd/cache/x.zip",
        "done": f"[{TS}][23:42:42] INFO [mxu_lib::commands::download] "
                f"download_file completed: 313755110 bytes -> E:/x/"
                f"MaaEnd-win-x86_64-v2.34.0.zip (session 2)",
        "install": f"[{TS}][23:42:43] INFO [mxu_lib::commands::update] apply_full_update called",
        "res": f"[{TS}][23:36:00] INFO [mxu_lib::commands::download] download_file: "
               f"https://example/resource-v1.2.3.zip -> E:/cache/resource-v1.2.3.zip",
    }
    cases = [
        ("空日志 ⇒ idle", "", "", None, "idle"),
        ("只有版本检查 ⇒ detecting", tauri_lines["detect"], "", None, "detecting"),
        ("已开始下载本体包 ⇒ downloading",
         tauri_lines["detect"] + "\n" + tauri_lines["start"], "", None, "downloading"),
        ("下完但还没装 ⇒ installing",
         tauri_lines["start"] + "\n" + tauri_lines["done"], "", None, "installing"),
        ("正在解压替换 ⇒ installing",
         tauri_lines["start"] + "\n" + tauri_lines["done"] + "\n" + tauri_lines["install"],
         "", None, "installing"),
        ("应用日志有「检测到刚更新完成」⇒ finished（压过 install）",
         tauri_lines["start"] + "\n" + tauri_lines["install"], app_fin, base, "finished"),
        ("**资源包**下载不算自我更新 ⇒ idle", tauri_lines["res"], "", None, "idle"),
        ("旧行被基线过滤 ⇒ idle",
         tauri_lines["install"].replace("23:42:43", "20:00:00"), "", base, "idle"),
        ("基线之后的行仍被识别 ⇒ installing",
         tauri_lines["install"], "", base, "installing"),
    ]
    for name, tt, app, bl, want in cases:
        got = Z.zmd_update_phase(tt, app, bl)["phase"]
        check(name, got == want, f"got={got} want={want}")

    # ---------------------------------------------------------------- 6)
    hr("[6] 闸门驱动：idle 放行 / detecting 宽限 / downloading 超时")
    logs = []
    real_probe = Z._zmd_update_probe
    real_grace, real_poll = Z.ZMD_UPDATE_DETECT_GRACE, Z.ZMD_UPDATE_POLL
    try:
        Z._zmd_update_probe = lambda logdir=None, baseline=None: {
            "phase": "idle", "evidence": [], "zip": None}
        t0 = time.perf_counter()
        r = Z.zmd_update_wait(None, logs.append, max_wait=5.0)
        check("idle ⇒ 立即 ready", r["state"] == "ready" and r["phase"] == "idle",
              f"{r['state']}/{r['phase']} {time.perf_counter() - t0:.1f}s")
        check("idle 不等待（<1s）", time.perf_counter() - t0 < 1.0)

        Z._zmd_update_probe = lambda logdir=None, baseline=None: {
            "phase": "finished", "evidence": ["检测到刚更新完成"], "zip": None}
        r = Z.zmd_update_wait(None, logs.append, max_wait=5.0)
        check("finished ⇒ 立即 ready（弹窗留给节点 6）",
              r["state"] == "ready" and r["phase"] == "finished")

        Z.ZMD_UPDATE_DETECT_GRACE, Z.ZMD_UPDATE_POLL = 0.4, 0.1
        Z._zmd_update_probe = lambda logdir=None, baseline=None: {
            "phase": "detecting", "evidence": ["找到匹配的 Release"], "zip": None}
        r = Z.zmd_update_wait(None, logs.append, max_wait=5.0)
        check("只有版本检查（detecting）⇒ 宽限后放行",
              r["state"] == "ready" and r["phase"] == "detecting_stale",
              f"{r['state']}/{r['phase']}")

        Z._zmd_update_probe = lambda logdir=None, baseline=None: {
            "phase": "downloading", "evidence": ["download_file"], "zip": None}
        r = Z.zmd_update_wait(None, logs.append, max_wait=0.5)
        check("downloading 不收敛 ⇒ timeout（不默认成功，INV-30）",
              r["state"] == "timeout" and r["phase"] == "downloading",
              f"{r['state']}/{r['phase']} waited={r['waited']}s")
    finally:
        Z._zmd_update_probe = real_probe
        Z.ZMD_UPDATE_DETECT_GRACE, Z.ZMD_UPDATE_POLL = real_grace, real_poll

    print("  闸门日志（前 8 行）：")
    for ln in logs[:8]:
        print("    " + ln)

    # ---------------------------------------------------------------- 7)
    hr("[7] 真实日志：应用日志发现 + 「检测到刚更新完成」标记")
    app_log = Z.zmd_app_log_path()
    if app_log is None:
        skip("应用日志发现", f"{Z.ZMD_LOGDIR} 下没有 <date>-<n>.log")
    else:
        print(f"  最新应用日志：{app_log}")
        check("文件名符合 <date>-<n>.log",
              bool(Z.ZMD_APP_LOG_RX.match(app_log.name)), app_log.name)
        txt = Z._zmd_app_log_text()
        check("应用日志可读且非空", len(txt) > 0, f"{len(txt)} 字符")
        if Z.ZMD_UPD_FINISHED.replace("\\", "") and "检测到刚更新完成" in txt:
            ph = Z.zmd_update_phase("", txt, None)
            check("真实日志里的更新完成标记能识别为 finished",
                  ph["phase"] == "finished", ph["phase"])
        else:
            skip("真实日志标记", "这份应用日志里没有「检测到刚更新完成」"
                              "（当前实例不是更新重启后的那次）")

    hr("汇总")
    if FAILS:
        print(f"  FAILED {len(FAILS)} 项：")
        for f in FAILS:
            print(f"    - {f}")
        return 1
    print("  ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
