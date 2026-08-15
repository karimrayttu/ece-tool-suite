"""Minimal pure-Python PNG encoder + a trace renderer (no Pillow dependency).

Used by the simulated scope/SA to answer :DISP:DATA? with a real PNG of the current trace,
so the screenshot pipeline is exercised end-to-end. Real Keysight instruments return their
own display PNG over the same endpoint.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """rgb = width*height*3 bytes (row-major, 8-bit RGB)."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # color type 2 = RGB
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 for the scanline
        raw.extend(rgb[y * stride:(y + 1) * stride])
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def render_trace_png(values, *, width: int = 480, height: int = 220, color=(245, 158, 11)) -> bytes:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (14, 20, 34)  # dark background
    for i in range(0, width, max(1, width // 10)):
        img[:, i] = (31, 41, 55)
    for j in range(0, height, max(1, height // 8)):
        img[j, :] = (31, 41, 55)

    v = np.asarray(values, dtype=np.float64)
    if v.size > 1:
        vmin, vmax = float(v.min()), float(v.max())
        if vmax == vmin:
            vmax = vmin + 1.0
        pad = (vmax - vmin) * 0.1
        vmin -= pad
        vmax += pad
        xs = np.linspace(0, width - 1, v.size).astype(int)
        ys = (height - 1 - ((v - vmin) / (vmax - vmin)) * (height - 1)).astype(int)
        ys = np.clip(ys, 0, height - 1)
        img[ys, xs] = color
        img[np.clip(ys - 1, 0, height - 1), xs] = color  # thicken
    return encode_png(width, height, img.tobytes())


def ieee_block(payload: bytes) -> bytes:
    """Wrap bytes in an IEEE-488.2 definite-length block (#<n><len><payload>)."""
    digits = str(len(payload))
    return f"#{len(digits)}{digits}".encode("ascii") + payload
