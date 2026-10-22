# -*- coding: utf-8 -*-
r"""验证 find_sidebar_item：从真实抓帧定位侧栏「任务」项。

真值（人眼读 002-task-loop-start.png，1458x800，ok-ww v3.7.4）：
    截图方式      y≈101
    实时触发      y≈141
    任务          y≈184   <- 目标
    角色代码      y≈223
    脚本          y≈261
    模板          y≈300
    计划任务      y≈340
    角色设置      y≈385
    游戏快捷键    y≈421

用法：
    & "D:\WORKs\Anaconda\python.exe" -X utf8 probe\_probe_sidebar_item.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator import match  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "logs", "runs", "run-20261015-191549", "shots")

# 期望：序号 -> (名称, y 真值)
EXPECT = [
    ("截图方式", 101),
    ("实时触发", 141),
    ("任务", 184),
    ("角色代码", 223),
    ("脚本", 261),
    ("模板", 300),
    ("计划任务", 340),
    ("角色设置", 385),
    ("游戏快捷键", 421),
]
TOL = 14   # 允许的 y 偏差（簇 cy 与文字视觉中心天然有差异）


def main():
    fails = 0
    for name in ("002-task-loop-start.png",):
        p = os.path.join(D, name)
        if not os.path.isfile(p):
            print(f"[缺文件] {p}")
            return 1
        rgb = np.asarray(Image.open(p).convert("RGB"))
        h, w = rgb.shape[:2]
        print("=" * 74)
        print(f"{name}  {w}x{h}")
        print("=" * 74)

        for idx, (label, y_true) in enumerate(EXPECT):
            res = match.find_sidebar_item(rgb, idx, log=None)
            if res is None:
                print(f"   [{idx}] {label:8s} 期望 y≈{y_true:4d}  -> 未定位  ✗")
                fails += 1
                continue
            _, y = res["pos"]
            ok = abs(y - y_true) <= TOL
            mark = "✅" if ok else "✗"
            if not ok:
                fails += 1
            print(f"   [{idx}] {label:8s} 期望 y≈{y_true:4d}  实际 y={y:4d}  "
                  f"{mark}   (列表 {res['n_items']} 项，行距 {res['pitch']})")

    print("\n" + "=" * 74)
    print("总判定：" + ("✅ 全部符合预期" if fails == 0 else f"❌ {fails} 项不符"))
    print("=" * 74)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
