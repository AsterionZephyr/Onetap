"""probe/_probe_gui2_drift.py — 验证「清单漂移守卫」真的会报警（不是空测）

节点链现在**属于每个程序**：orchestrator/apps/<key>/nodes/__init__.py 的 NODES。
本探针模拟"有人只改了某个程序的清单、没同步节点文件"：

流程：备份 zmd 的 NODES -> 把某条 Node 的 name 改成不存在的 step6_renamed_probe
      -> verify_against_disk() 必须报「缺专属实现」+「目录里多出未登记文件」
      -> 还原 -> 再确认干净。
      另测「目录里多出一个清单没登记的 step*.py」。

全程 try/finally 还原，绝不把仓库留在漂移状态。
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MANIFEST = os.path.join(ROOT, "orchestrator", "apps", "zmd", "nodes", "__init__.py")
BAK = MANIFEST + ".driftbak"
NODES_DIR = os.path.dirname(MANIFEST)
EXTRA = os.path.join(NODES_DIR, "step99_bogus.py")


def problems():
    import importlib
    import gui.chain as c
    importlib.reload(c)          # 同时清掉模块内的 (mtime,size) 缓存
    return c.verify_against_disk()


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


print("=" * 70)
print("清单漂移守卫：验证它会报警（按程序清单，不是硬编码表）")
print("=" * 70)

base_ok = True
drift_ok = False
extra_ok = False
final_ok = False

shutil.copyfile(MANIFEST, BAK)
try:
    base = problems()
    print(f"\n1. 基线（未改动）            : {len(base)} 处问题")
    base_ok = (len(base) == 0)
    if not base_ok:
        for p in base:
            print("   " + p)

    # 改 Node 的 name（语法合法）—— 模拟"改了清单没同步节点文件"
    src = read(MANIFEST)
    assert '"step6_first_frame"' in src
    write(MANIFEST, src.replace('"step6_first_frame"',
                                '"step6_renamed_probe"', 1))

    drift = problems()
    print(f"\n2. 改 zmd 清单里的 Node name: {len(drift)} 处问题")
    for p in drift:
        print("   " + p)
    drift_ok = (any("缺专属实现" in p and "step6_renamed_probe" in p
                    for p in drift)
                and any("未登记" in p for p in drift))
    print(f"\n   => 报出「缺专属实现」且「原文件成了未登记」: {drift_ok}")

    # 再加一个"目录里多出文件"的情形（先还原清单）
    write(MANIFEST, src)
    write(EXTRA, "# probe\n")
    try:
        drift2 = problems()
        print(f"\n3. 目录里多出 step99_bogus : {len(drift2)} 处问题")
        for p in drift2:
            print("   " + p)
        extra_ok = any("未登记" in p and "step99_bogus" in p for p in drift2)
        print(f"\n   => 报警未登记文件: {extra_ok}")
    finally:
        os.remove(EXTRA)
finally:
    shutil.move(BAK, MANIFEST)

final = problems()
print(f"\n4. 还原后                    : {len(final)} 处问题")
for p in final:
    print("   " + p)
final_ok = (len(final) == 0)

good = base_ok and drift_ok and extra_ok and final_ok
print("\n" + "=" * 70)
print("守卫有效" if good else "守卫有问题")
sys.exit(0 if good else 1)
