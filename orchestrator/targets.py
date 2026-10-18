"""targets — 目标程序的**清单与顺序**，以及 `--target` 表达式的解析

## 为什么单独一个模块

`--target` 的合法取值原先**硬编码在 4 处**（都要改一遍才加得上第 3 个程序）：

    orchestrator/steps/main.py:112   choices=["ww", "nte", "both"]
    orchestrator/steps/main.py:368   order = ["ww", "nte"]
    orchestrator/steps/context.py:435 choices=["ww", "nte"]
    gui/app.py                       TARGET_CHOICES / TARGET_ARG

加一个应用就要在 4 个地方同步，漏一个的后果是**静默跑错程序**
（命令行接受但语义不同 / GUI 显示有但传不下去）。

现在：清单的**唯一来源**是 `orchestrator/programs.py` 的 `ALL`
（加应用 = 在那边加一条 `Program`），顺序 = `ALL` 的声明顺序。
本模块只负责三件事：

  1. **顺序**：`keys()` 就是默认执行顺序 = `ALL` 的声明顺序 = **MaaEnd → ok-ww → ok-nte**
     （2026-10-19 用户裁定：串联时 MaaEnd 必须排第一，它出问题不影响下一个应用）
  2. **解析**：接受 `ww` / `nte` / `ww,nte` / `nte,ww` / `all` / `both`
  3. **报错**：未知 key **响亮失败**，绝不静默回落默认程序

## 表达式语法

    省略              -> 全部（按 ALL 顺序）           ← 只在"算顺序"时用
    ww                -> [ww]
    nte               -> [nte]
    ww,nte / nte,ww   -> 按**书写顺序**跑（不是 ALL 顺序！用户可能想先跑 nte）
    all / both        -> 全部（按 ALL 顺序 = MaaEnd, ok-ww, ok-nte）；`both` 是历史写法，永久保留
    重复项            -> 去重，保留首次出现的位置
    空串 / 全逗号     -> TargetError
    未知 key          -> TargetError，错误信息里列出全部已知 key

⚠️ 刻意**不**支持 `-` 排除语法（`all,-nte`）：排除式在"想跑全部但漏了一个"
的情况下与打错一个 key 长得一样，而两者后果截然不同。多写两个 key 而已。

## 一个容易踩的坑

`parse(None)` 返回全部 —— 这只用于"排顺序"。命令行上**省略 --target
不等于跑全部**，它的语义是"跟随 state.json 里记录的那个程序"
（见 `context.program_key`：省略时读 state.json，再退默认）。
这两件事不要混：`main.py` 里是 `picked = targets.parse(args.target)`，
**只在 `args.target` 非空时**才走多目标。
"""

from . import programs

# `both` 是 2026-10 定的历史写法，已经被写进文档、定时任务、探针命令里，
# 不能删 —— 但两程序之外它没有意义，故与 `all` 同义。
ALIASES_ALL = ("all", "both")

_SEPS = (",", "，", "+", " ")   # 容错：中文逗号、加号、空格都当分隔符


class TargetError(ValueError):
    """--target 表达式不合法。"""


def keys():
    """全部目标程序的 key，顺序 = programs.ALL 的声明顺序。"""
    return [p.key for p in programs.ALL]


def displays():
    """key -> 显示名（"ok-ww" 这种）。"""
    return {p.key: p.display for p in programs.ALL}


def split(spec):
    """把表达式拆成 token 列表（不做校验）。纯函数，便于测试。"""
    if spec is None:
        return []
    out, buf = [], spec
    for sep in _SEPS[1:]:
        buf = buf.replace(sep, _SEPS[0])
    for tok in buf.split(_SEPS[0]):
        tok = tok.strip()
        if tok:
            out.append(tok)
    return out


def parse(spec, *, allow_empty=False):
    """把 `--target` 表达式解析成 key 列表（去重、保序）。

    `spec` 为 None/空串 -> 全部（调用方请确认这就是你要的语义，见模块 docstring）。
    `allow_empty=True` -> None/空串返回 []（供"没选任何目标"的调用方使用）。
    """
    toks = split(spec)
    if not toks:
        if allow_empty:
            return []
        if spec is not None and str(spec).strip():
            raise TargetError(
                f"--target {spec!r} 里没有有效的程序名；已知：{keys()}")
        return keys()

    known = keys()
    picked = []
    alias_hit = [t for t in toks if t.lower() in ALIASES_ALL]
    if alias_hit:
        if len(toks) > 1:
            raise TargetError(
                f"--target {spec!r} 把 {alias_hit[0]!r}（= 全部）和其他程序名混用了；"
                f"要么只写 {alias_hit[0]}，要么逐个列出：{','.join(known)}")
        return list(known)

    for tok in toks:
        if tok not in known:
            aliases = " 或 ".join(ALIASES_ALL)
            raise TargetError(
                f"未知的目标程序 {tok!r}；已知：{known}"
                f"（全部 = {aliases}）")
        if tok not in picked:
            picked.append(tok)
    return picked


def ordered(spec=None):
    """parse 的别名：返回执行顺序。"""
    return parse(spec)


def describe(spec):
    """给日志用的一句话："ww,nte" -> "ok-ww → ok-nte"。"""
    disp = displays()
    if spec is None or not str(spec).strip():
        picked = keys()
    else:
        try:
            picked = parse(spec)
        except TargetError:
            return str(spec)
    return " → ".join(disp.get(k, k) for k in picked)


def validate_choices_flag(text):
    """`--target` 的单程序校验：一个 step 只能跑一个程序。

    节点级命令行（context.add_common_args）用它：那里传 `ww,nte` 是**歧义**
    （这个节点该操作谁？），不能像主控那样拆成多轮，必须报错。
    """
    picked = parse(text)
    if len(picked) != 1:
        raise TargetError(
            f"单个节点只能有一个目标程序，收到 {text!r} -> {picked}；"
            f"要跑多个程序请用主控：python -m orchestrator.steps.main --target {text}")
    return picked[0]


def self_check():
    """自检：清单一致 + 表达式解析。返回问题列表（空 = 全过）。"""
    problems = []
    ks = keys()
    if not ks:
        problems.append("programs.ALL 为空")
    if len(set(ks)) != len(ks):
        problems.append(f"programs.ALL 里有重复 key：{ks}")

    cases = [
        (None, ks),
        ("", ks),
        ("all", ks),
        ("both", ks),
        ("  ", ks),
        ("ww", ["ww"]),
        (ks[0], [ks[0]]),
        (",".join(ks), ks),
        (",".join(reversed(ks)), list(reversed(ks))),
        ("，".join(ks), ks),                      # 中文逗号
        ("+".join(ks), ks),                       # 加号
        (",".join(ks + ks), ks),                  # 去重
    ]
    for spec, want in cases:
        try:
            got = parse(spec)
        except TargetError as e:
            problems.append(f"parse({spec!r}) 意外报错：{e}")
            continue
        if got != want:
            problems.append(f"parse({spec!r}) -> {got}，应为 {want}")

    # 用户裁定（2026-10-19）：串联默认顺序的第一个必须是 MaaEnd。
    # 这不是审美 —— 它最可能失败，排在后面会把前两个程序的成果和机器状态一起赔进去。
    if ks and ks[0] != "zmd":
        problems.append(f"默认串联顺序的第一个不是 MaaEnd（zmd）：{ks}")

    bad = ["nope", "ww,nope", "all,ww"]
    for spec in bad:
        try:
            parse(spec)
        except TargetError:
            pass
        else:
            problems.append(f"parse({spec!r}) 应当报错但没报")
    return problems


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m orchestrator.targets",
        description="列出 / 校验目标程序清单")
    ap.add_argument("--list", action="store_true", help="列出全部目标程序")
    ap.add_argument("--parse", default=None, metavar="EXPR",
                    help="解析一个 --target 表达式并打印结果")
    ap.add_argument("--self-check", action="store_true", help="跑自检")
    args = ap.parse_args(argv)

    if args.self_check:
        problems = self_check()
        for p in problems:
            print(f"[FAIL] {p}")
        print("OK" if not problems else f"{len(problems)} 处问题")
        return 0 if not problems else 1
    if args.parse is not None:
        try:
            print(",".join(parse(args.parse)))
        except TargetError as e:
            print(f"[ERROR] {e}")
            return 2
        return 0
    for i, p in enumerate(programs.ALL, 1):
        print(f"  {i}. {p.key:6s} {p.display:10s} {p.exe}")
    print(f"\n全部 = {','.join(keys())}（也接受 {' / '.join(ALIASES_ALL)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
