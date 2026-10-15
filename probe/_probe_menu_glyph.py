"""探针：程序化 ☰ 检测（find_menu_glyph）的正负样本验证。

背景（FRAMEWORK §4.4 / INV-34 / INV-38 / INV-39）：
  旧身份锚点是 `1_ww.png` + 硬编码窗口内坐标 (16,215)，取自 1822x1000。
  实测在 1458x800（出现过的最小尺寸）下只得 0.3962，导致节点 6/8 双双失败。
  本探针验证**程序化检测**（三条等距水平亮线）在各尺寸下都能正确定位，
  且能拒绝非 ok-ww 的帧。

用法：
    python probe/_probe_menu_glyph.py
"""
import os
import sys

sys.path.insert(0, '.')
import numpy as np
from PIL import Image

from orchestrator import match

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(rel):
    return np.array(Image.open(os.path.join(ROOT, rel)).convert('RGB'))


# --- 正样本：真 ok-ww 在不同尺寸/页面下 --------------------------------
POSITIVE = [
    ('ok-ww 参考帧 1875x1250', r'probe\running-000.png'),
    ('ok-ww 另一帧 obs-000', r'probe\obs-000.png'),
    ('ok-ww okww-now', r'probe\okww-now.png'),
    ('ok-ww 1458x800 关于页', r'logs\shots\bg-verify-002.png'),
    ('ok-ww 抓帧(临时运行目录)',
     r'C:\Users\99462\AppData\Local\Temp\chaintest\shots\002-first-frame.png'),
]

# --- 负样本：非 ok-ww --------------------------------------------------
NEGATIVE = [
    ('DSH 终端 003', r'C:\Users\99462\AppData\Local\Temp\chaintest\shots\003-task-loop-start.png'),
    ('DSH 终端 001', r'C:\Users\99462\AppData\Local\Temp\chaintest\shots\001-first-frame.png'),
    ('GUI 截图 gui-chk', r'logs\shots\gui-chk.png'),
    ('GUI 截图 gui-ctl', r'logs\shots\gui-ctl.png'),
    ('GUI 截图 gui-now', r'logs\shots\gui-now.png'),
]


def report(name, want, frame):
    g = match.find_menu_glyph(frame)
    act = 'ACCEPT' if g else 'REJECT'
    ok = (act == want)
    if g:
        detail = 'pos=%-10s bbox=%-18s 线长=%-3s 间距=%s score=%.3f' % (
            g['pos'], g['bbox'], g['line_len'], g['gaps'], g['score'])
    else:
        detail = ''
    print('  %-30s %-7s -> %-7s %s  %s' % (
        name, want, act, '✅' if ok else '❌ 不符', detail))
    return ok


def main():
    print('=' * 112)
    print('程序化 ☰ 检测（find_menu_glyph）—— 必须「接受真 ok-ww、拒绝其他一切窗口」')
    print('=' * 112)

    allok = True
    print('\n[正样本] 真 ok-ww（尺寸/页面各异，必须 ACCEPT）')
    for name, rel in POSITIVE:
        try:
            f = load(rel)
        except Exception as e:
            print('  %-30s 读不了: %s' % (name, e))
            allok = False
            continue
        allok &= report('%s %dx%d' % (name, f.shape[1], f.shape[0]), 'ACCEPT', f)

    print('\n[负样本] 非 ok-ww（必须 REJECT）')
    for name, rel in NEGATIVE:
        try:
            f = load(rel)
        except Exception as e:
            print('  %-30s 读不了: %s' % (name, e))
            continue
        allok &= report('%s %dx%d' % (name, f.shape[1], f.shape[0]), 'REJECT', f)

    # --- 合成负样本 ---------------------------------------------------
    print('\n[合成负样本] 人工构造，验证判据不被平凡满足')
    # 1) 纯黑帧
    black = np.zeros((800, 1458, 3), dtype=np.uint8)
    allok &= report('纯黑帧 800x1458', 'REJECT', black)
    # 2) 纯白帧（全亮，但无结构）
    white = np.full((800, 1458, 3), 255, dtype=np.uint8)
    allok &= report('纯白帧 800x1458', 'REJECT', white)
    # 3) 把真 ok-ww 帧的 ☰ 区域涂黑 —— 残余结构不得被误认成 ☰
    src = load(r'logs\shots\bg-verify-002.png')
    erased = src.copy()
    erased[50:75, 10:40] = 0
    allok &= report('ok-ww 帧但抹掉 ☰ 区域', 'REJECT', erased)
    # 4) 把 ☰ 区域整块替换为**随机噪声**
    rng = np.random.default_rng(12345)
    noisy = src.copy()
    noisy[50:75, 10:40] = rng.integers(0, 256, (25, 30, 3), dtype=np.uint8)
    allok &= report('ok-ww 帧但 ☰ 区域换成噪声', 'REJECT', noisy)
    # 5) 只有两条线（少了第三条）
    two = src.copy()
    two[68:70, 17:32] = 0
    allok &= report('ok-ww 帧但只剩两条线', 'REJECT', two)
    # 6) 三条线但**不等距**（第三条下移 6px）
    uneven = src.copy()
    uneven[68:70, 17:32] = 0
    uneven[74:76, 17:32] = src[68:70, 17:32]
    allok &= report('ok-ww 帧但三线不等距', 'REJECT', uneven)

    print('\n' + '=' * 112)
    print('总判定：%s' % ('✅ 全部符合预期' if allok else '❌ 有不符合项'))
    print('=' * 112)
    return 0 if allok else 1


if __name__ == '__main__':
    raise SystemExit(main())
