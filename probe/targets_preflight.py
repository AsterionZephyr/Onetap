r"""串联测试前的**只读**体检：按执行顺序逐程序看「现在能不能跑」。

与 zmd_preflight.py 的分工：那个是 MaaEnd 冷启动专用（要求 app **未**运行）；
这个是三程序串联用的 —— 程序已在跑也能开跑（节点 2 会等它），所以「在运行」
只作提示，不算失败。

判 BAD 的只有三件事（任一不满足，串联跑到该程序必然白跑）：
  1. 没提权（两程序都是 requireAdministrator，节点点不动 / 杀不掉）
  2. 第一层 exe 不存在（程序没装 / 路径变了）
  3. 运行日志目录或日志文件不存在（判据层要靠它裁决完成，缺了只能 UNKNOWN）

**只读**：不启动、不点击、不改文件（日志只 stat + 读尾部 4KB）。

用法：
    D:\WORKs\Anaconda\python.exe probe\targets_preflight.py
    D:\WORKs\Anaconda\python.exe probe\targets_preflight.py --target zmd,ww,nte
"""
import argparse
import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import programs, targets, verdict, win32, window  # noqa: E402

bad = []


def line(tag, ok, text):
    print(f"[{'OK ' if ok else 'BAD'}] {tag:<14} {text}")
    if not ok:
        bad.append(tag)


def newest_log(prog):
    """最新一份运行日志。

    目录**不能**读 prog.logdir：ok-ww / ok-nte 的 logdir 是 None，真实目录由
    verdict._logdir_for 按 <root>/data/apps/ok-<key>/working/logs 推出来
    （MaaEnd 才显式 override 成 debug/）。照抄 prog.logdir 会得到 None ⇒
    探针自己坏掉、却报「程序日志不可达」的假问题 —— 本探针第一版就这么错过一次。
    """
    d = str(verdict._logdir_for(prog))
    if not os.path.isdir(d):
        return None
    pat = getattr(prog, "log_glob", None) or "ok-script*.log"
    hits = glob.glob(os.path.join(d, pat))
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--target", default="zmd,ww,nte",
                    help="按此顺序体检（默认 = 串联建议顺序）")
    args = ap.parse_args(argv)
    order = targets.parse(args.target)

    print("=== 串联测试前体检 ===")
    print("时间:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("顺序:", " -> ".join(programs.get(k).display for k in order))
    print()

    admin = win32.is_admin()
    for key in order:
        prog = programs.get(key)
        print(f"--- {prog.display}（{key}）---")
        line("提权", admin, "is_admin()=%s" % admin)
        line("exe 存在", os.path.isfile(prog.exe), prog.exe)

        procs = [p for p in win32.list_processes(prog.process_names)
                 if p[2] and prog.owns_process(p[2])]
        if procs:
            print(f"[---] 程序在运行  {[(p[0], p[1]) for p in procs]}")
        else:
            print("[---] 程序未运行  节点 2 会自己拉起（第一层）")

        w = window.find_window(prog)
        if w:
            # find_window 只返回 hwnd/pid/title/class（没有 rect）——
            # 想打尺寸得另外问 win32.window_state，别去 w["rect"] 里取（会静默得到 None）
            r = win32.window_state(w["hwnd"])["rect"]
            print(f"[---] 已有窗口  hwnd={w['hwnd']} class={w['class']!r} "
                  f"title={w['title']!r} {r['width']}x{r['height']}")
        else:
            print("[---] 暂无窗口")

        lp = newest_log(prog)
        if lp:
            st = os.stat(lp)
            with open(lp, "rb") as fh:
                fh.seek(max(0, st.st_size - 4096))
                tail = fh.read()
            last = tail.decode("utf-8", "replace").strip().splitlines()[-1:] or ["<空>"]
            line("日志可达", True, "%s  %d B  mtime=%s" % (
                os.path.basename(lp), st.st_size,
                datetime.datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M:%S")))
            print("     最后一行:", last[0][:140])
        else:
            probs = verdict.logdir_self_check(prog.key)
            line("日志可达", False, "%s / %s（%s）" % (
                verdict._logdir_for(prog),
                getattr(prog, "log_glob", None) or "ok-script*.log",
                "; ".join(probs) or "首次运行后会创建"))

        g = [p for p in win32.list_processes(prog.game_names)] if prog.game_names else []
        print(f"[---] 游戏进程  {[p[0] for p in g] or '无'}")
        print()

    if bad:
        print("结论: %d 项不满足 —— %s" % (len(bad), ", ".join(bad)))
        return 1
    print("结论: 可以按上面的顺序串联开跑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
