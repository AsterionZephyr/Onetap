"""探针：第一层（启动器 shell）的可见性与可清除性 —— FAULT #34。

## 背景

`process_prefix` 原先只指向**第二层** `data/apps/<name>/`，而两个程序的
**第一层** `*.exe` 都装在 `root_dir` 下、`process_prefix` **之上**：

    ok-nte : E:\\TOOLS\\ScriptsGames\\ok-nte\\ok-nte.exe          <- 不在 prefix 下
             E:\\TOOLS\\ScriptsGames\\ok-nte\\data\\apps\\ok-nte  <- prefix 指向这

于是 `owns_process(第一层) == False` ⇒ 框架**看不见第一层**。两个后果
（2026-10-17 实机坐实）：

1. **残留 shell 劫持下一次运行**：ok-nte 第一层是 Tauri 启动器，界面上有
   「▶ 启动应用」按钮；第一层**不会**自行退出，实测 pid 26892 存活 48s 以上。
   它持有的窗口标题就是 `ok-nte`（类 `Tauri Window`），停在「启动应用」
   等点击 —— 它**不会**替我们把第二层拉起来。
2. **杀不掉**：`window.running()` 对它返回空 ⇒ 前置清理与收尾都清不掉它，
   故障一轮一轮复现。

## 本探针守什么（全部离线，不启动任何进程）

| 组 | 断言 |
| --- | --- |
| 1 | 两条判据并存：`owns_process` 同时认「prefix 前缀」与「first_layer_exe 精确相等」 |
| 2 | 两程序第一层都 `owns=True`；第二层 pythonw 也 `owns=True`（两层都认） |
| 3 | **绝不串台**：任一程序都不认对方的第一层（FAULT #32 型回归） |
| 4 | `first_layer_exe` 是**精确相等**判据，不是根目录前缀 —— 用同目录下
      的另一个 exe（如 `ok-nte-something.exe`）反证不被认领 |
| 5 | `programs.self_check()` 在正常现场返回 `[]`，且能报出人为破坏的归属判据 |
| 6 | `find_window` 仍**排除** Tauri 外壳窗口（第一层可见 ≠ 第一层可用作目标） |

## 跑法（在仓库根）

    python -X utf8 probe\\_probe_first_layer_ownership.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import programs  # noqa: E402

FAIL = []
N = [0]


def check(cond, label, detail=""):
    N[0] += 1
    if cond:
        print("  [OK] %s" % label)
    else:
        print("  [NG] %s%s" % (label, ("  <- " + detail) if detail else ""))
        FAIL.append(label)


def main():
    print("=" * 74)
    print("FAULT #34 探针：第一层的可见性与可清除性")
    print("=" * 74)

    # --- 1. 两条判据并存 -----------------------------------------------------
    import inspect
    src = inspect.getsource(programs.Program.owns_process)
    print("\n[1] owns_process 必须同时用两条判据")
    check("process_prefix" in src, "判据含 process_prefix（第二层）")
    check("first_layer_exe" in src, "判据含 first_layer_exe（第一层）")
    check("startswith(" in src, "第二层用前缀匹配")
    check("==" in src, "第一层用精确相等（不能用根目录前缀，否则串台）")

    # --- 2. 两层都认 ---------------------------------------------------------
    print("\n[2] 两层都必须被认领")
    for p in programs.ALL:
        check(p.owns_process(p.exe), "%s 第一层被认领" % p.display,
              p.exe)
        second = os.path.join(p.root_dir, "data", "apps", "ok-" + p.key,
                              "python", "pythonw.exe")
        if os.path.isfile(second):
            check(p.owns_process(second), "%s 第二层被认领" % p.display, second)
        else:
            # 第二层 python 不在磁盘上也应能按前缀判定
            check(p.owns_process(second),
                  "%s 第二层路径按前缀被认领（文件不存在也成立）" % p.display,
                  second)

    # --- 3. 绝不串台 ---------------------------------------------------------
    print("\n[3] 绝不认对方的第一层（FAULT #32 型回归）")
    for p in programs.ALL:
        for q in programs.ALL:
            if p is q:
                continue
            check(not p.owns_process(q.exe),
                  "%s 不认 %s 的第一层" % (p.display, q.display), q.exe)

    # --- 4. 第一层是精确相等，不是根目录前缀 ---------------------------------
    print("\n[4] 第一层判据必须是精确相等，不是根目录前缀")
    for p in programs.ALL:
        # 同 root_dir 下造一个别的 exe 名
        sibling = os.path.join(p.root_dir, "ok-%s-something-else.exe" % p.key)
        check(not p.owns_process(sibling),
              "%s 不认同目录下的其它 exe（证明不是根目录前缀）" % p.display,
              sibling)
        # 大小写不敏感（Win32 路径）
        check(p.owns_process(p.exe.upper()),
              "%s 第一层判据大小写不敏感" % p.display)

    # --- 5. self_check -------------------------------------------------------
    print("\n[5] programs.self_check() 覆盖归属判据")
    check(programs.self_check() == [], "正常现场 self_check() 返回 []",
          repr(programs.self_check()))
    saved = programs.NTE.first_layer_exe
    try:
        programs.NTE.first_layer_exe = r"e:\nonexistent\ok-nte.exe"
        bad = programs.self_check()
        check(any("第一层" in b for b in bad),
              "人为破坏 first_layer_exe 时报出「认不出第一层」", repr(bad))
        check(any("FAULT #34" in b for b in bad),
              "报错文案点明 FAULT #34")
    finally:
        programs.NTE.first_layer_exe = saved

    # --- 6. 第一层可见 ≠ 第一层可用作目标 ------------------------------------
    print("\n[6] find_window 仍必须排除 Tauri 外壳")
    import inspect as _i
    fsrc = _i.getsource(__import__("orchestrator.window",
                                   fromlist=["x"]).find_window)
    check("TAURI_CLASS" in fsrc, "find_window 排除 Tauri 外壳类")
    check("QT_CLASS_PREFIX" in fsrc, "find_window 要求窗口类是 Qt 系")
    check(programs.TAURI_CLASS == "Tauri Window",
          "TAURI_CLASS 常量未被改动", programs.TAURI_CLASS)

    print()
    print("=" * 74)
    if FAIL:
        print("失败 %d / %d 项：" % (len(FAIL), N[0]))
        for f in FAIL:
            print("  - %s" % f)
        return 1
    print("全部 %d 项通过" % N[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
