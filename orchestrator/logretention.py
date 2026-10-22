"""orchestrator.logretention — 运行目录保留策略（只留最近 N 轮）

## 为什么要有这个模块

`logs/runs/` 每跑一次就多一个目录，实测 78 轮堆到 37.9 MB / 988 个文件，
而其中真正会再被翻看的只有最近几轮。用户裁定：**只保留最近十次**。

## 保留判据是**目录名里的时间戳**，不是 mtime

目录名形如 `run-20261022-195300`（运行时**开始**时刻）。mtime 会倒挂——
实测 `run-20261019-055729` 里的文件写到了 2026-10-20 00:40 本地，按 mtime
排序它反而排在 `run-20261020-004125` 前面。名字是唯一稳定且人能读的键。

## 默认只管 `run-<YYYYMMDD-HHMMSS>`，不碰手工命名的目录

`fault35-ww/`、`stalled-live-20261018-061325/` 这类是调查时**手工起名**的
目录，自动删它们等于替人决定丢哪份现场。要一起清就用 `--all`（一次性整理
时用过一次），日常轮转与 GUI 自动清理都只处理时间戳目录。

## 谁在调它

  - GUI：每次编排结束（`gui/app.py` 的 `on_finished`）在后台线程里
    `sweep_silently()` —— 不弹窗、不阻塞界面、任何异常都吞掉。清不干净
    不该影响"这一轮跑完了没有"这个结论。
  - 手工：`python -X utf8 -m orchestrator.logretention`（默认 dry-run，
    加 `--apply` 才删；`--index` 打印 Markdown 表格，用来刷新
    `docs/RUN-INDEX.md`）。

## 与"证据"的关系

被删的轮次仍可能被 `docs/FAULT-LOG.md` / `docs/HISTORY.md` 用编号点名
（实测 45 处）。删目录不删引用——正文里的 run-id 是**历史叙事**，改成
"已清理"等于改写历史。长期索引在 `docs/RUN-INDEX.md`，磁盘上的目录只是
"还没清理掉"的那几轮。

⚠️ 本模块**只用标准库**，不 import win32 / programs / capture。
GUI 是跳板，编排代码坏掉时它必须还能起来（见 `gui/runner.py` 开头的理由）。
"""

import os
import re
import shutil
import sys
import time

# 目录名在这里被当作唯一排序键：run-YYYYMMDD-HHMMSS
RUN_PREFIX = "run-"
KEEP_DEFAULT = 10

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_runs_dir():
    return os.path.join(ROOT, "logs", "runs")


# ---------------------------------------------------------------- 目录信息

def _looks_like_run(name):
    """`run-20261022-195300` 这种形如时间戳的手工目录名才算"轮次"。"""
    if not name.startswith(RUN_PREFIX):
        return False
    stamp = name[len(RUN_PREFIX):]
    return (len(stamp) == 15 and stamp[8] == "-"
            and stamp[:8].isdigit() and stamp[9:].isdigit())


def _walk_size(path):
    """(文件数, 字节数, 最新文件 mtime)。读不到的条目算 0，不抛异常。"""
    files = 0
    total = 0
    newest = 0.0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            files += 1
            try:
                st = os.stat(os.path.join(dirpath, fn))
            except OSError:
                continue
            total += st.st_size
            if st.st_mtime > newest:
                newest = st.st_mtime
    return files, total, newest


def _stamp_of(text):
    """`YYYYMMDD-HHMMSS` -> `YYYY-MM-DD HH:MM:SS`（只格式化，不复排）。"""
    return "%s-%s-%s %s:%s:%s" % (text[0:4], text[4:6], text[6:8],
                                  text[9:11], text[11:13], text[13:15])


# 手工命名的目录里也可能带时间戳：stalled-live-20261019-024608、fault35-e2e（没有）
_NAME_TS = re.compile(r"(20\d{6})-?(\d{6})")


def stamp_from_name(name):
    """从目录名里抠出 `YYYYMMDD-HHMMSS`；没有返回 None。"""
    m = _NAME_TS.search(name)
    return (m.group(1) + "-" + m.group(2)) if m else None


def _start_text(name, when):
    """`when` 是"这一轮的开始时刻"：时间戳目录用名字，手工命名的用最新文件 mtime。

    为什么不用**目录的** mtime：实测 2026-10-22 23:31 一次目录级拷贝把
    `fault34-e2e` 等手工目录的 mtime 全刷成了拷贝时刻，而里面的文件 mtime 保留着。
    """
    if _looks_like_run(name):
        return _stamp_of(name[len(RUN_PREFIX):])
    stamp = stamp_from_name(name)
    if stamp:
        return _stamp_of(stamp)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))


def entries(runs_dir=None):
    """列出 `runs/` 下的一级目录，按**开始时间倒序**（最新在前）。

    每项：{name, path, start, sort_key, mtime, files, bytes, is_run, programs}
    """
    runs_dir = runs_dir or default_runs_dir()
    out = []
    try:
        names = os.listdir(runs_dir)
    except OSError:
        return out
    for name in names:
        path = os.path.join(runs_dir, name)
        if not os.path.isdir(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        is_run = _looks_like_run(name)
        files, size, newest = _walk_size(path)
        # 排序键统一成 `YYYYMMDD-HHMMSS` 形状，两种目录才能混在一起排：
        # 时间戳目录用名字（唯一稳定键），手工目录用最新文件 mtime（见 _start_text）。
        if is_run:
            sort_key = name[len(RUN_PREFIX):]
            when = 0.0
        else:
            # 手工目录：名字里带时间就用名字（那是运行时刻），否则退到最新文件 mtime
            named = stamp_from_name(name)
            when = newest or mtime
            sort_key = named or time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
        out.append({
            "name": name,
            "path": path,
            "start": _start_text(name, when),
            "sort_key": sort_key,
            "mtime": mtime,
            "files": files,
            "bytes": size,
            "is_run": is_run,
            "programs": _programs_of(path),
        })
    out.sort(key=lambda d: d["sort_key"], reverse=True)
    return out


def _programs_of(path):
    """这次跑了哪几个程序：串联看子目录名，单程序读根 state.json 的 program。"""
    import json

    names = []
    try:
        kids = sorted(os.listdir(path))
    except OSError:
        kids = []
    for kid in kids:
        sub = os.path.join(path, kid)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "state.json")):
            names.append(kid)
    if names:
        return names
    try:
        with open(os.path.join(path, "state.json"), "r", encoding="utf-8") as f:
            prog = json.load(f).get("program")
        return [prog] if prog else []
    except (OSError, ValueError):
        return []


# ---------------------------------------------------------------- 保留策略

def plan(runs_dir=None, keep=KEEP_DEFAULT, include_all=False):
    """返回 (保留清单, 待删清单)。`include_all=False` 时手工目录不进删除清单。"""
    if keep < 1:
        raise ValueError("keep 至少为 1（0 等于删光，不做这种默认行为）")
    items = entries(runs_dir)
    eligible = [d for d in items if include_all or d["is_run"]]
    kept = eligible[:keep]
    kept_names = {d["name"] for d in kept}
    doomed = [d for d in eligible if d["name"] not in kept_names]
    return kept, doomed


def prune(runs_dir=None, keep=KEEP_DEFAULT, include_all=False, apply=False):
    """按保留策略清理。`apply=False` 只报告。返回结果字典，不抛异常。"""
    runs_dir = runs_dir or default_runs_dir()
    kept, doomed = plan(runs_dir, keep, include_all)
    report = {
        "runs_dir": runs_dir,
        "keep": keep,
        "kept": [d["name"] for d in kept],
        "deleted": [],
        "errors": [],
        "freed_bytes": 0,
        "apply": bool(apply),
    }
    if not apply:
        report["deleted"] = [d["name"] for d in doomed]
        report["freed_bytes"] = sum(d["bytes"] for d in doomed)
        return report

    for d in doomed:
        try:
            shutil.rmtree(d["path"])
        except OSError as e:
            report["errors"].append("%s: %s" % (d["name"], e))
            continue
        report["deleted"].append(d["name"])
        report["freed_bytes"] += d["bytes"]
    return report


def sweep_silently(runs_dir=None, keep=KEEP_DEFAULT):
    """给 GUI 用的：失败一律吞掉，返回报告或 None。

    GUI 在编排结束后调它。清理是**附带动作**——失败不该冒泡成界面上的错误，
    更不该阻塞界面（调用方放在 daemon 线程里）。
    """
    try:
        return prune(runs_dir, keep=keep, include_all=False, apply=True)
    except Exception:                      # noqa: BLE001 —— 见 docstring
        return None


# ---------------------------------------------------------------- 索引输出

def _state_summary(path):
    """读一个运行目录下所有 state.json，给出「程序 通过/总数（失败的节）」摘要。"""
    import json

    parts = []
    candidates = []
    try:
        for kid in sorted(os.listdir(path)):
            sub = os.path.join(path, kid)
            if os.path.isdir(sub):
                candidates.append((kid, os.path.join(sub, "state.json")))
    except OSError:
        pass
    if not any(os.path.isfile(p) for _l, p in candidates):
        # 单程序运行把 state.json 放在目录根下；串联时根目录那份是主控自己的，
        # 与各程序子目录的 state.json 重复，不要混进来（会出现「本目录 0/1」）。
        candidates = [("", os.path.join(path, "state.json"))]

    for label, state_path in candidates:
        if not os.path.isfile(state_path):
            continue
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            parts.append("%s state.json 不可读" % (label or "?"))
            continue
        steps = raw.get("steps") or {}
        if not steps:
            parts.append("%s 无节点记录" % (label or "?"))
            continue
        ok = sum(1 for r in steps.values() if r.get("status") == "ok")
        bad = [sid for sid, r in steps.items() if r.get("status") not in ("ok", "running")]
        name = label or raw.get("program") or "主控"
        if bad:
            parts.append("%s %d/%d（节点 %s 未通过）" % (name, ok, len(steps), ",".join(sorted(bad))))
        else:
            parts.append("%s %d/%d" % (name, ok, len(steps)))
    return " · ".join(parts) if parts else "无 state.json"


def markdown_index(runs_dir=None):
    """Markdown 表格：供 `docs/RUN-INDEX.md` 使用（写盘由调用方决定）。"""
    items = entries(runs_dir)
    lines = ["| 运行目录 | 开始 | 文件 | 大小 | 程序 | 结果 |",
             "| --- | --- | ---: | ---: | --- | --- |"]
    for d in items:
        lines.append("| `%s` | %s | %d | %s | %s | %s |" % (
            d["name"], d["start"], d["files"], _fmt_size(d["bytes"]),
            "、".join(d["programs"]) or "—", _state_summary(d["path"])))
    return "\n".join(lines)


def _fmt_size(n):
    if n >= 1024 * 1024:
        return "%.1fM" % (n / 1048576.0)
    if n >= 1024:
        return "%.0fK" % (n / 1024.0)
    return "%dB" % n


# ---------------------------------------------------------------- CLI

USAGE = """用法（在仓库根执行）：

  python -X utf8 -m orchestrator.logretention                 # 只看将删什么
  python -X utf8 -m orchestrator.logretention --apply         # 真删
  python -X utf8 -m orchestrator.logretention --keep 5
  python -X utf8 -m orchestrator.logretention --all --apply   # 连手工命名的目录一起清
  python -X utf8 -m orchestrator.logretention --index         # 打印 Markdown 索引

默认保留最近 """ + str(KEEP_DEFAULT) + """ 轮（按 run-YYYYMMDD-HHMMSS 名字排序）。
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    keep = KEEP_DEFAULT
    apply = False
    include_all = False
    index = False

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(USAGE)
            return 0
        if a == "--apply":
            apply = True
        elif a == "--all":
            include_all = True
        elif a == "--index":
            index = True
        elif a == "--keep":
            i += 1
            if i >= len(argv) or not argv[i].isdigit():
                print("--keep 需要一个整数", file=sys.stderr)
                return 2
            keep = int(argv[i])
        else:
            print("未知参数：%s\n\n%s" % (a, USAGE), file=sys.stderr)
            return 2
        i += 1

    if index:
        print(markdown_index())
        return 0

    if keep < 1:
        print("--keep 至少为 1", file=sys.stderr)
        return 2

    rep = prune(keep=keep, include_all=include_all, apply=apply)
    print("运行目录：%s" % rep["runs_dir"])
    print("策略：保留最近 %d 轮（%s）" % (
        keep, "含手工命名目录" if include_all else "只算 run-YYYYMMDD-HHMMSS"))
    print("")
    print("[保留] %d 个" % len(rep["kept"]))
    for name in rep["kept"]:
        print("    %s" % name)
    print("")
    print("%s %d 个，合计 %s" % ("[已删]" if apply else "[将删]", len(rep["deleted"]),
                                 _fmt_size(rep["freed_bytes"])))
    for name in rep["deleted"]:
        print("    %s" % name)
    if rep["errors"]:
        print("")
        print("⚠ 有 %d 个删不掉：" % len(rep["errors"]))
        for e in rep["errors"]:
            print("    %s" % e)
    if not apply and rep["deleted"]:
        print("")
        print("（dry-run；确认后加 --apply）")
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
