import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import capture as C
C.user32.SetProcessDPIAware()

print("=== N-3 深挖：离屏抓帧为何不报错 ===")
for name,x,y,w,h in [
    ("屏内 (100,100)",100,100,80,80),
    ("右越界 (2500,100)",2500,100,200,80),
    ("完全离屏 (10000,10000)",10000,10000,80,80),
    ("负坐标 (-500,-500)",-500,-500,80,80),
]:
    got = C.capture_region(x,y,w,h)
    if got is None:
        print(f"  [{name}] -> None（已被检出）")
    else:
        d,fw,fh = got
        st = C.frame_stats(d,fw,fh)
        print(f"  [{name}] -> {fw}x{fh} 均值{st['mean_rgb']} 色彩{st['distinct_colors_sampled']}")

print()
print("=== 结论 ===")
print("BitBlt 对越界区域返回成功，GetDIBits 也返回行数，")
print("故窗口外的抓帧会静默产出全黑/垃圾帧，不报错。")
print("=> INV-12 必须做「内容校验」，不能只信 API 返回值。")
