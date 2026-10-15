"""docs/_probe_gui2_drift.py — 验证「清单漂移守卫」真的会报警（不是空测）

第一次的两次尝试都被 PowerShell 的 -replace 搞坏了编码，结果走到
"SyntaxError 分支"而不是"不一致分支"。这里用 Python 自己改文件，编码可控。

流程：备份 main.py -> 改 CHAIN 里的**模块名**（语法仍合法）-> 看检查结果
      -> 还原 -> 再确认干净。
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MAIN = os.path.join(ROOT, "orchestrator", "steps", "main.py")
BAK = MAIN + ".driftbak"


def problems():
    import importlib
    import gui.chain as c
    importlib.reload(c)
    return c.verify_against_disk()


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


print("=" * 70)
print("清单漂移守卫：验证它会报警")
print("=" * 70)

shutil.copyfile(MAIN, BAK)
try:
    base = problems()
    print(f"\n1. 基线                     : {len(base)} 处问题")

    # 改模块名（语法合法）—— 模拟"有人只改了 steps/main.py 没改 gui/chain.py"
    src = read(MAIN)
    assert "step6_first_frame" in src
    write(MAIN, src.replace('"step6_first_frame"', '"step6_renamed_probe"'))

    drift = problems()
    print(f"2. 改了 main.py 的 CHAIN    : {len(drift)} 处问题")
    for p in drift:
        print("   " + p.replace("\n", "\n   "))

    ok_drift = len(drift) == 1 and "不一致" in drift[0]
    print(f"\n   => 报警且指明是不一致: {ok_drift}")

    # 再加一个"目录里多出文件"的情形
    write(MAIN, src)                       # 先还原 CHAIN
    extra = os.path.join(os.path.dirname(MAIN), "step99_bogus.py")
    write(extra, "# probe\n")
    try:
        drift2 = problems()
        print(f"\n3. 目录里多出 step99_bogus : {len(drift2)} 处问题")
        for p in drift2:
            print("   " + p)
        ok_extra = any("未登记" in p for p in drift2)
        print(f"\n   => 报警未登记文件: {ok_extra}")
    finally:
        os.remove(extra)
finally:
    shutil.move(BAK, MAIN)

final = problems()
print(f"\n4. 还原后                   : {len(final)} 处问题")

good = (len(base) == 0 and ok_drift and ok_extra and len(final) == 0)
print("\n" + "=" * 70)
print("守卫有效" if good else "守卫有问题")
sys.exit(0 if good else 1)
