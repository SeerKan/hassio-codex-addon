from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    rows = []
    for y in range(height):
        start = y * width
        row = b"".join(bytes(pixel) for pixel in pixels[start : start + width])
        rows.append(b"\x00" + row)
    raw = b"".join(rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def make_icon(size: int = 128) -> list[tuple[int, int, int, int]]:
    pixels = []
    cx = cy = size / 2
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5 / (size / 2)
            bg = max(0, min(1, 1 - dist))
            r = int(17 + bg * 30)
            g = int(20 + bg * 76)
            b = int(22 + bg * 66)
            a = 255
            if 34 < x < 94 and 38 < y < 90:
                border = x in range(35, 39) or x in range(90, 94) or y in range(39, 43)
                border = border or y in range(86, 90)
                if border:
                    r, g, b = 72, 198, 169
            if 48 < x < 58 and 56 < y < 66:
                r, g, b = 245, 193, 92
            if 70 < x < 80 and 56 < y < 66:
                r, g, b = 245, 193, 92
            if 52 < x < 77 and 75 < y < 79:
                r, g, b = 242, 245, 243
            pixels.append((r, g, b, a))
    return pixels


def make_logo(width: int = 250, height: int = 100) -> list[tuple[int, int, int, int]]:
    pixels = []
    for y in range(height):
        for x in range(width):
            r, g, b = 17, 20, 22
            if x < 96:
                shade = int(32 * (1 - abs(y - height / 2) / (height / 2)))
                r, g, b = 25 + shade, 31 + shade, 34 + shade
            if 24 < x < 76 and 24 < y < 76:
                border = x in range(25, 29) or x in range(72, 76)
                border = border or y in range(25, 29) or y in range(72, 76)
                if border:
                    r, g, b = 72, 198, 169
            if 39 < x < 47 and 42 < y < 50:
                r, g, b = 245, 193, 92
            if 55 < x < 63 and 42 < y < 50:
                r, g, b = 245, 193, 92
            if 42 < x < 61 and 59 < y < 62:
                r, g, b = 242, 245, 243
            if 112 < x < 222 and 34 < y < 42:
                r, g, b = 72, 198, 169
            if 112 < x < 236 and 56 < y < 62:
                r, g, b = 242, 245, 243
            pixels.append((r, g, b, 255))
    return pixels


def main() -> None:
    write_png(ROOT / "codex_agent" / "icon.png", 128, 128, make_icon())
    write_png(ROOT / "codex_agent" / "logo.png", 250, 100, make_logo())


if __name__ == "__main__":
    main()
