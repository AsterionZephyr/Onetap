"""探针：验证「用 Start-Process 起的独立进程」是否脱离 DSH 宿主存活。

用途：无人值守长跑必须不依赖我的持续在场。若 DSH 桌面应用退出，
我这一轮就结束；只有**独立进程**（父进程为 explorer/services，而非
pwsh/DeepSeek Harness）才能把编排跑完。

本脚本被启动后每秒往 argv[1] 追加一行时间戳，共 8 秒。
"""

import sys
import time

out = sys.argv[1]
with open(out, "w", encoding="utf-8") as f:
    for i in range(8):
        f.write(f"{i} {time.strftime('%H:%M:%S')}\n")
        f.flush()
        time.sleep(1)
