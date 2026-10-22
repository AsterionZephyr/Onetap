"""_check_workspace.py — 工作区目录契约 + 文档一致性的只读门禁（exit≠0 即违约）。

七条判据：

  C1 根目录**文件**只有 README.md / AGENTS.md / .gitignore（目录另由 C3 管）
  C2 docs/ 下只有 .md 文件、adr/、img/ —— 探针与配图不得住在文档目录
  C3 README.md 的「## 目录」表逐行对齐实际一级目录（表 ⇄ 树，双向）
  C4 无 gitignore 垃圾残留（%SystemDrive%/、probe-shots/、debug.log、_pyout.txt…）
  C5 文档内部相对链接全部有效（.md 里 ](./x.md) 指向的路径必须存在）
  C6 「共 N 条 / 十二条」类声明与实际条目数一致（HANDOFF §2.1 / §2.2、FRAMEWORK §1）
  C7 引用可解析：INV-nn、FAULT #nn、硬性规则 n 都能找到定义处
     （反向查孤儿不变量：只报不拦）

约定见 docs/adr/0006-workspace-directory-contract.md（C1~C4）与
docs/adr/0007-doc-layering-single-source.md（C5~C7）。

跑法（仓库根，无需管理员，不启动任何目标程序）：

    python -X utf8 probe/_check_workspace.py

退出码：0 = 全部通过；1 = 至少一条违约（逐条打印原因）。
本脚本**只读**：只 stat / listdir / 读 md 与 .gitignore，不写盘、不删、不建。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROOT_FILES_OK = {"README.md", "AGENTS.md", ".gitignore"}
DOCS_FILES_SUFFIX_OK = {".md"}
DOCS_DIRS_OK = {"adr", "img"}
TOP_LEVEL_SKIP = {".git", ".dsh-tmp", "__pycache__"}
# C3：这两份文件由 C1 管，README 的开篇用文字交代它们，不进「## 目录」表
TOC_SKIP = {"README.md", "AGENTS.md"}
# C5/C7 遍历时跳过的目录：不是本仓库的现行文档/代码
SCAN_SKIP_DIRS = {".git", ".dsh-tmp", "__pycache__", "node_modules", "logs", "legacy"}

# C4：这些路径出现即违约（全部来自一次性的本机事故或临时输出，不应存在于仓库）
JUNK = [
    "%SystemDrive%",
    "probe-shots",
    "debug.log",
    ".dsh-tmp/gitversion.txt",
    "probe/_pyout.txt",
]

README = ROOT / "README.md"
TOC_HEADING = "## 目录"


def c1_root_files() -> list[str]:
    bad = []
    for p in ROOT.iterdir():
        if p.name in TOP_LEVEL_SKIP or p.is_dir():
            continue
        if p.name not in ROOT_FILES_OK:
            bad.append(f"根目录多出文件：{p.name}")
    for name in ROOT_FILES_OK:
        if not (ROOT / name).is_file():
            bad.append(f"根目录缺少文件：{name}")
    return bad


def c2_docs_only_docs() -> list[str]:
    docs = ROOT / "docs"
    if not docs.is_dir():
        return ["docs/ 不存在"]
    bad = []
    for p in sorted(docs.iterdir()):
        if p.is_dir():
            if p.name not in DOCS_DIRS_OK:
                bad.append(f"docs/ 多出目录：{p.name}/")
            continue
        if p.suffix.lower() not in DOCS_FILES_SUFFIX_OK:
            bad.append(f"docs/ 多出非文档文件：{p.name}")
    return bad


def _toc_paths() -> list[str]:
    """解析 README 的「## 目录」表，取第一列里所有反引号路径。"""
    text = README.read_text(encoding="utf-8")
    if TOC_HEADING not in text:
        return []
    section = text.split(TOC_HEADING, 1)[1]
    # 到下一个二级标题为止
    section = re.split(r"\n## ", section, maxsplit=1)[0]
    found = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        for token in re.findall(r"`([^`]+)`", cells[0]):
            found.append(token)
    return found


def c3_toc_matches_tree() -> list[str]:
    mentioned: set[str] = set()
    for raw in _toc_paths():
        if "://" in raw:
            continue
        first = raw.replace("\\", "/").split("/")[0].strip()
        if first:
            mentioned.add(first)

    actual: set[str] = set()
    for p in ROOT.iterdir():
        if p.name in TOP_LEVEL_SKIP or p.name in TOC_SKIP or p.name.startswith("."):
            continue
        actual.add(p.name)

    bad = []
    for name in sorted(actual - mentioned):
        bad.append(f"README「## 目录」漏写：{name}")
    for name in sorted(mentioned - actual):
        bad.append(f"README「## 目录」写了不存在的：{name}")
    return bad


def c4_no_junk() -> list[str]:
    bad = []
    for rel in JUNK:
        if (ROOT / rel).exists():
            bad.append(f"垃圾残留：{rel}")
    for p in ROOT.rglob("_pyout.txt"):
        if ".git" not in p.parts:
            bad.append(f"垃圾残留：{p.relative_to(ROOT).as_posix()}")
    return bad


# --------------------------------------------------------------------------- #
# C5 / C6 / C7：文档一致性（ADR 0007）
# --------------------------------------------------------------------------- #

def _scannable(rel_parts: tuple[str, ...]) -> bool:
    return not any(part in SCAN_SKIP_DIRS for part in rel_parts)


def _md_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.md")
        if _scannable(p.relative_to(ROOT).parts)
    )


def _code_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.py")
        if _scannable(p.relative_to(ROOT).parts)
    )


def _strip_code_fences(text: str) -> str:
    """去掉 ``` 围栏里的内容：围栏里常贴命令行，不是可点的链接。"""
    out, in_fence = [], False
    for line in text.splitlines():
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def c5_md_links_resolve() -> list[str]:
    bad = []
    for f in _md_files():
        text = _strip_code_fences(f.read_text(encoding="utf-8"))
        for m in re.finditer(r"\]\(([^)\s]+)\)", text):
            target = m.group(1)
            if re.match(r"^(https?|mailto):", target) or target.startswith("#"):
                continue
            raw = target.split("#", 1)[0]
            if not raw:
                continue
            raw = raw.replace("%20", " ").replace("\\", "/")
            if not (f.parent / raw).resolve().exists():
                bad.append(f"{f.relative_to(ROOT).as_posix()} → {target}（路径不存在）")
    return bad


def _section(text: str, heading: str) -> str:
    """取 heading 之后、到下一个同级或更高级标题之前的内容。"""
    i = text.find(heading)
    if i < 0:
        return ""
    level = len(heading) - len(heading.lstrip("#"))
    rest = text[i + len(heading):]
    m = re.search(r"\n#{1,%d} " % level, rest)
    return rest[: m.start()] if m else rest


def c6_count_claims() -> list[str]:
    bad = []
    handoff = (ROOT / "docs/HANDOFF.md").read_text(encoding="utf-8")

    # §2.1 静默失效全表：「共 N 条」 vs 实际表格行数
    sec21 = _section(handoff, "### 2.1")
    claim = re.search(r"共 (\d+) 条", sec21)
    rows = len(re.findall(r"^\| \d+ \|", sec21, re.M))
    if not claim:
        bad.append("HANDOFF §2.1 抬头缺少「共 N 条」声明")
    elif int(claim.group(1)) != rows:
        bad.append(f"HANDOFF §2.1 声明「共 {claim.group(1)} 条」，实际 {rows} 行")

    # §2.2 硬性规则：「十二条」 vs 实际编号条目数
    sec22 = _section(handoff, "### 2.2")
    items = len(re.findall(r"^\d+\. ", sec22, re.M))
    if "十二条" in handoff and items != 12:
        bad.append(f"HANDOFF §2.2 标题写「十二条硬性规则」，实际 {items} 条")

    # FRAMEWORK §1 不变量：编号必须 1..N 连续无重复
    fw = (ROOT / "docs/FRAMEWORK.md").read_text(encoding="utf-8")
    nums = [int(n) for n in re.findall(r"^\| INV-(\d+) \|", _section(fw, "## 1. 不变量"), re.M)]
    if not nums:
        bad.append("FRAMEWORK §1 没解析到任何 `| INV-n |` 行")
    else:
        top = max(nums)
        if sorted(nums) != list(range(1, top + 1)):
            bad.append(f"FRAMEWORK §1 的 INV 编号不连续或有重复（最大 INV-{top}，实有 {len(nums)} 行）")
        # 跨文件的「INV-1..INV-N」总条数声明
        for f in _md_files():
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"INV-1[.．]{1,2}INV-(\d+)", text):
                if int(m.group(1)) != top:
                    bad.append(
                        f"{f.relative_to(ROOT).as_posix()} 写「INV-1..INV-{m.group(1)}」，"
                        f"而 FRAMEWORK §1 实际到 INV-{top}"
                    )
    return bad


def c7_refs_resolve() -> list[str]:
    bad = []
    fw = (ROOT / "docs/FRAMEWORK.md").read_text(encoding="utf-8")
    fl = (ROOT / "docs/FAULT-LOG.md").read_text(encoding="utf-8")

    inv_defined = {int(n) for n in re.findall(r"^\| INV-(\d+) \|", _section(fw, "## 1. 不变量"), re.M)}
    # 故障编号的"定义处"= 索引表行（| #A / #B | ...）与标题行（## FAULT #A / #B ...）：
    # 同一个编号可能藏在「#A / #B」这种合并写法里，所以按行收集而不是单点匹配。
    fault_defined: set[int] = set()
    for line in fl.splitlines():
        if line.startswith("## ") or re.match(r"^\| #\d", line):
            fault_defined |= {int(n) for n in re.findall(r"#(\d+)", line)}
    rule_defined = {int(n) for n in re.findall(
        r"^(\d+)\. ", _section((ROOT / "docs/HANDOFF.md").read_text(encoding="utf-8"), "### 2.2"), re.M)}

    inv_used: set[int] = set()
    sources = [(f, f.read_text(encoding="utf-8")) for f in _md_files() + _code_files()]
    for f, text in sources:
        rel = f.relative_to(ROOT).as_posix()
        for n in (int(x) for x in re.findall(r"\bINV-(\d+)\b", text)):
            inv_used.add(n)
            if n not in inv_defined:
                bad.append(f"{rel} 引用了不存在的 INV-{n}")
        for m in re.finditer(r"FAULT #(\d+)\s*[~–—-]\s*#?(\d+)", text):
            lo, hi = int(m.group(1)), int(m.group(2))
            for n in range(min(lo, hi), max(lo, hi) + 1):
                if n not in fault_defined:
                    bad.append(f"{rel} 引用了不存在的 FAULT #{n}（区间 #{lo}~#{hi}）")
        for n in (int(x) for x in re.findall(r"FAULT #(\d+)", text)):
            if n not in fault_defined:
                bad.append(f"{rel} 引用了不存在的 FAULT #{n}")
        for n in (int(x) for x in re.findall(r"硬性规则 (\d+)", text)):
            if n not in rule_defined:
                bad.append(f"{rel} 引用了不存在的硬性规则 {n}")

    orphans = sorted(inv_defined - inv_used)
    if orphans:
        print(f"       [note] 未被任何文档/代码引用的不变量（孤儿，不拦）："
              f"{', '.join('INV-%d' % n for n in orphans)}")
    return bad


CHECKS = [
    ("C1 根目录只有 README.md / AGENTS.md / .gitignore", c1_root_files),
    ("C2 docs/ 只放文档（.md + adr/ + img/）", c2_docs_only_docs),
    ("C3 README「## 目录」表 ⇄ 实际一级目录", c3_toc_matches_tree),
    ("C4 无 gitignore 垃圾残留", c4_no_junk),
    ("C5 文档内部相对链接全部有效", c5_md_links_resolve),
    ("C6「共 N 条」类声明与实际条目数一致", c6_count_claims),
    ("C7 INV-nn / FAULT #nn / 硬性规则 n 引用可解析", c7_refs_resolve),
]


def main() -> int:
    failed = 0
    for title, fn in CHECKS:
        problems = fn()
        if problems:
            failed += 1
            print(f"[FAIL] {title}")
            for msg in problems:
                print(f"       - {msg}")
        else:
            print(f"[ OK ] {title}")
    print()
    if failed:
        print(f"违约 {failed}/{len(CHECKS)} 条 —— 工作区不符合目录契约")
        return 1
    print(f"全部 {len(CHECKS)} 条通过 —— 工作区符合目录契约")
    return 0


if __name__ == "__main__":
    sys.exit(main())
