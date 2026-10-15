"""纯标准库 PNG 写出 —— 环境无 Pillow/numpy，故自带。

用于把 BGRA 原始帧落盘，供肉眼复核（INV-12 要求"抓图后校验帧内容"，
而色彩统计只能筛出全黑，不能确认"抓到的是 ok-ww 而不是别的窗口"）。
"""

import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png_bgra(path: str, data: bytes, w: int, h: int) -> None:
    """把 BGRA 缓冲写成 PNG（RGB，无 alpha）。"""
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)                       # 每行 filter = None
        row = data[y * stride:(y + 1) * stride]
        # BGRA -> RGB
        for x in range(0, stride, 4):
            raw.append(row[x + 2])
            raw.append(row[x + 1])
            raw.append(row[x])

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8bit truecolor
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
