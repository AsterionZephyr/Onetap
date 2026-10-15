"""template_probe.py — 模板与当前窗口的几何关系测绘（只读，不点击）

回答三个问题：
  1. 模板尺寸 vs 当前窗口尺寸  -> INV-3 / INV-4 是否会被触发
  2. 模板能否在当前帧中匹配到  -> 匹配位置与置信度
  3. 匹配区域的像素是否真的对应 -> 肉眼复核的裁图落盘
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from PIL import Image

import capture as C

TPL_DIR = Path(r"E:\TOOLS\ScriptsGames\Onetap\templates")
OUT_DIR = Path(r"E:\TOOLS\ScriptsGames\Onetap\probe")


def capture_okww():
    C.user32.SetProcessDPIAware()
    wins = C.find_okww_window()
    if not wins:
        print("[NG] 未找到 ok-ww 窗口")
        sys.exit(1)
    hwnd, pid, title = wins[0]
    r = C.get_window_rect(hwnd)
    ww, wh = r.right - r.left, r.bottom - r.top
    got = C.capture_region(r.left, r.top, ww, wh)
    if got is None:
        print("[NG] 抓帧失败")
        sys.exit(1)
    data, fw, fh = got
    arr = np.frombuffer(data, dtype=np.uint8).reshape(fh, fw, 4)
    rgb = arr[:, :, [2, 1, 0]]          # BGRA -> RGB
    return (hwnd, pid, title, r, fw, fh, rgb)


def match_template(frame_rgb, tpl_rgb):
    """归一化互相关匹配（纯 numpy，无 cv2）。返回 (score, x, y)。

    ⚠️ **实测修复（INV-40）**：早期实现用"粗步长 4 扫描 + 在粗最优附近 ±6 细化"。
    该做法**会漏掉真实峰**：若真实位置不在粗最优的 ±6 邻域内，细化阶段
    根本不会访问它，于是**静默返回错误位置与偏低分数**。
    实测症状：把帧自身的一块切下来当模板，手工 NCC 在该位置为 **1.0000**，
    而旧函数返回 **0.6086 @ 错误位置** —— 自匹配都不能得 1.0。

    实现（精确，且足够快）：
      - 窗口和 / 平方和：积分图 O(1)
      - 模板与窗口的点积：**FFT 互相关**（`scipy` 不可用，故用 numpy.fft 手写）
    不使用 `sliding_window_view` —— 大模板时会尝试分配上百 GiB。
    """
    fh, fw, _ = frame_rgb.shape
    th, tw, _ = tpl_rgb.shape
    if th > fh or tw > fw:
        return None

    f = frame_rgb.astype(np.float64).mean(axis=2)
    t = tpl_rgb.astype(np.float64).mean(axis=2)
    t_centered = t - t.mean()
    t_norm = float(np.sqrt((t_centered ** 2).sum()))
    if t_norm == 0:
        return None

    n = th * tw
    ny, nx = fh - th + 1, fw - tw + 1

    # --- 1) 窗口和 与 窗口平方和（积分图，O(1) 每窗口）---
    ii = np.zeros((fh + 1, fw + 1))
    ii[1:, 1:] = f.cumsum(axis=0).cumsum(axis=1)
    ii2 = np.zeros((fh + 1, fw + 1))
    ii2[1:, 1:] = (f * f).cumsum(axis=0).cumsum(axis=1)

    def box(I):
        return (I[th:th + ny, tw:tw + nx] - I[0:ny, tw:tw + nx]
                - I[th:th + ny, 0:nx] + I[0:ny, 0:nx])

    wsum = box(ii)
    wsum2 = box(ii2)
    wmean = wsum / n
    wvar = np.maximum(wsum2 - n * wmean * wmean, 0.0)
    wnorm = np.sqrt(wvar)

    # --- 2) 模板与窗口的点积：FFT 互相关 ---
    # corr[y,x] = sum_{i,j} f[y+i, x+j] * t[i, j]
    # ⚠️ 不要给 rfft2/irfft2 传 `s=` 做补零：那样 irfft2 的归一化因子
    #    与实际补零尺寸不匹配，结果会被放大（实测放大到 7e6）。
    #    改为**显式补零**到 (fy, fx) 后再变换。
    fy, fx = fh + th - 1, fw + tw - 1
    Fp = np.zeros((fy, fx))
    Fp[:fh, :fw] = f
    Tp = np.zeros((fy, fx))
    Tp[:th, :tw] = t[::-1, ::-1]
    conv = np.fft.irfft2(np.fft.rfft2(Fp) * np.fft.rfft2(Tp), s=(fy, fx))
    corr = conv[th - 1:th - 1 + ny, tw - 1:tw - 1 + nx]

    # --- 3) 归一化 ---
    # 分子 = Σ (窗口 - 窗口均值)·(模板 - 模板均值)
    #      = corr - n·窗口均值·**模板原始均值**
    # ⚠️ 必须用 t.mean()（原始均值），不能 t_centered.mean()（恒为 ~0，
    #    会把中心化项整项消掉，导致分子偏大、分数爆表 —— 实测到 1e8）。
    numer = corr - n * wmean * t.mean()
    denom = wnorm * t_norm
    with np.errstate(divide="ignore", invalid="ignore"):
        scores = np.where(denom > 0, numer / denom, -2.0)

    idx = int(np.argmax(scores))
    y, x = divmod(idx, nx)
    return float(scores[y, x]), int(x), int(y)


def main():
    hwnd, pid, title, r, fw, fh, frame = capture_okww()
    print("=" * 64)
    print("模板 × 当前窗口 几何测绘（只读）")
    print("=" * 64)
    print(f"ok-ww  hwnd={hwnd} pid={pid}")
    print(f"       标题 = {title}")
    print(f"       窗口 rect = ({r.left},{r.top})-({r.right},{r.bottom})  =>  {fw} x {fh}")

    for name in sorted(TPL_DIR.glob("*.png")):
        print("\n" + "-" * 64)
        tpl = np.array(Image.open(name).convert("RGB"))
        th, tw, _ = tpl.shape
        print(f"[{name.name}]  模板尺寸 {tw} x {th}")

        # --- INV-4：出生尺寸/尺寸同源 ---
        if tw > fw or th > fh:
            print(f"   [!!] 模板比窗口还大（{tw}>{fw} 或 {th}>{fh}）—— 根本不可能匹配")
            continue
        if tw == fw:
            print(f"   [OK] 模板宽度 == 窗口宽度（{tw}）—— 疑似全宽行模板")
        else:
            print(f"   [!!] 模板宽度 {tw} != 窗口宽度 {fw}（差 {fw-tw}）")
            print(f"        => 该模板**不是**在当前尺寸窗口下采集的（INV-3/INV-4 情形）")

        # --- 匹配 ---
        res = match_template(frame, tpl)
        if res is None:
            print("   匹配：无法进行")
            continue
        score, mx, my = res
        print(f"   最佳匹配：score={score:.4f}  位置=({mx},{my})")
        if score > 0.9:
            verdict = "高度可信"
        elif score > 0.7:
            verdict = "中等"
        else:
            verdict = "不可信"
        print(f"   判定：{verdict}")

        # --- 裁出匹配区域供肉眼复核 ---
        cx0, cy0 = max(0, mx - 5), max(0, my - 5)
        cx1, cy1 = min(fw, mx + tw + 5), min(fh, my + th + 5)
        crop = frame[cy0:cy1, cx0:cx1]
        outp = OUT_DIR / f"match-{name.stem}.png"
        Image.fromarray(crop).save(outp)
        print(f"   裁图落盘：{outp.name}  ({cx1-cx0}x{cy1-cy0})  区域=({cx0},{cy0})-({cx1},{cy1})")

        # --- 若使用会用到的点击坐标 ---
        cx, cy = mx + tw // 2, my + th // 2
        print(f"   中心点（窗口内坐标）= ({cx},{cy})")
        print(f"   折算屏幕坐标 = ({r.left + cx},{r.top + cy})")


if __name__ == "__main__":
    main()
