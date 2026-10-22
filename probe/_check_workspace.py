"""_check_workspace.py — 工作区目录契约的只读门禁（exit≠0 即违约）。

四条判据（约定见 docs/adr/0006-workspace-directory-contract.md）：

  C1 根目录**文件**只有 README.md / AGENTS.md / .gitignore（目录另由 C3 管）
  C2 docs/ 下只有 .md 文件、adr/、img/ —— 探针与配图不得住在文档目录
  C3 README.md 的「## 目录」表逐行对齐实际一级目录（表 ⇄ 树，双向）
  C4 无 gitignore 垃圾残留（%SystemDrive%/、probe-shots/、debug.log、_pyout.txt…）

跑法（仓库根，无需管理员，不启动任何目标程序）：

    python -X utf8 probe/_check_workspace.py

退出码：0 = 全部通过；1 = 至少一条违约（逐条打印原因）。
本脚本**只读**：只 stat / listdir / 读 README 与 .gitignore，不写盘、不删、不建。
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


CHECKS = [
    ("C1 根目录只有 README.md / AGENTS.md / .gitignore", c1_root_files),
    ("C2 docs/ 只放文档（.md + adr/ + img/）", c2_docs_only_docs),
    ("C3 README「## 目录」表 ⇄ 实际一级目录", c3_toc_matches_tree),
    ("C4 无 gitignore 垃圾残留", c4_no_junk),
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
