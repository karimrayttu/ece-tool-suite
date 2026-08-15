"""Keysight waveform preamble + data decoding — pure, pyvisa-free.

This is the heart of the "sim -> real is a config swap" claim (M0 Spike C). The same
:func:`decode_waveform` turns raw bytes into scaled (time, volts) arrays whether those
bytes came from a real ``:WAVeform:DATA?`` query or from the SimTransport, because the
scaling depends only on the preamble, not on the transport.

Reference: Keysight InfiniiVision / InfiniiVision-X programmer's guide,
:WAVeform:PREamble? returns 10 comma-separated fields:

    format, type, points, count, xincrement, xorigin, xreference,
    yincrement, yorigin, yreference

Scaling (per Keysight programmer's guide):
    time[n]    = xorigin + (n - xreference) * xincrement
    voltage[n] = (raw[n] - yreference) * yincrement + yorigin

BYTE format -> 1 unsigned byte/point; WORD format -> 2 bytes/point with byte order set by
:WAVeform:BYTeorder (LSBFirst default on Keysight). Data is unsigned by default.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Keysight :WAVeform:FORMat numeric codes
FORMAT_BYTE = 0
FORMAT_WORD = 1
FORMAT_ASCII = 2  # (a.k.a. 4 on some models); handled separately, not via raw block


@dataclass(frozen=True)
class Preamble:
    fmt: int
    wtype: int
    points: int
    count: int
    xincrement: float
    xorigin: float
    xreference: float
    yincrement: float
    yorigin: float
    yreference: float

    @property
    def bytes_per_point(self) -> int:
        if self.fmt == FORMAT_BYTE:
            return 1
        if self.fmt == FORMAT_WORD:
            return 2
        raise ValueError(f"raw decode not applicable for format code {self.fmt}")


def parse_preamble(text: str) -> Preamble:
    """Parse the comma-separated ``:WAVeform:PREamble?`` response string."""
    parts = [p.strip() for p in text.strip().split(",")]
    if len(parts) != 10:
        raise ValueError(
            f"expected 10 preamble fields, got {len(parts)}: {text!r}"
        )
    return Preamble(
        fmt=int(float(parts[0])),
        wtype=int(float(parts[1])),
        points=int(float(parts[2])),
        count=int(float(parts[3])),
        xincrement=float(parts[4]),
        xorigin=float(parts[5]),
        xreference=float(parts[6]),
        yincrement=float(parts[7]),
        yorigin=float(parts[8]),
        yreference=float(parts[9]),
    )


def parse_definite_length_block(raw: bytes) -> bytes:
    """Strip the IEEE 488.2 definite-length block header: ``#<n><len><payload>``.

    Example: ``#800001000<1000 bytes>`` -> the 1000 payload bytes. A leading newline /
    whitespace and a trailing newline terminator (common from instruments) are tolerated.
    """
    data = raw.lstrip(b" \t\r\n")
    if not data[:1] == b"#":
        raise ValueError(f"not an IEEE definite-length block (no '#'): {raw[:16]!r}")
    ndigits = int(data[1:2])
    if ndigits == 0:
        # indefinite-length block: payload runs to a trailing newline
        return data[2:].rstrip(b"\r\n")
    start = 2 + ndigits
    length = int(data[2:start])
    payload = data[start:start + length]
    if len(payload) != length:
        raise ValueError(
            f"block truncated: header said {length} bytes, got {len(payload)}"
        )
    return payload


def decode_waveform(
    raw_block: bytes,
    pre: Preamble,
    *,
    byteorder: str = "LSB",
    signed: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Decode a raw ``:WAVeform:DATA?`` block into (time_s, volts) arrays using ``pre``.

    ``raw_block`` may include the ``#nDDD...`` header (it is stripped automatically).
    """
    payload = parse_definite_length_block(raw_block)

    if pre.fmt == FORMAT_BYTE:
        dtype = np.dtype(np.int8 if signed else np.uint8)
    elif pre.fmt == FORMAT_WORD:
        base = "i2" if signed else "u2"
        prefix = "<" if byteorder.upper().startswith("LSB") else ">"
        dtype = np.dtype(prefix + base)
    else:
        raise ValueError(f"decode_waveform handles BYTE/WORD only, not format {pre.fmt}")

    codes = np.frombuffer(payload, dtype=dtype)
    if codes.size and pre.points and codes.size >= pre.points:
        codes = codes[: pre.points]

    n = np.arange(codes.size, dtype=np.float64)
    t = pre.xorigin + (n - pre.xreference) * pre.xincrement
    v = (codes.astype(np.float64) - pre.yreference) * pre.yincrement + pre.yorigin
    return t, v


def encode_waveform_block(volts: np.ndarray, pre: Preamble, *, byteorder: str = "LSB") -> bytes:
    """Inverse of :func:`decode_waveform`: build a raw ``:WAVeform:DATA?``-style block from
    a volts array, given a preamble. Used by the SimTransport so simulated captures take the
    exact same decode path as real ones. Returns the bytes *with* the IEEE header."""
    codes_f = (np.asarray(volts, dtype=np.float64) - pre.yorigin) / pre.yincrement + pre.yreference

    if pre.fmt == FORMAT_BYTE:
        codes = np.clip(np.round(codes_f), 0, 255).astype(np.uint8)
        payload = codes.tobytes()
    elif pre.fmt == FORMAT_WORD:
        codes = np.clip(np.round(codes_f), 0, 65535).astype(np.uint16)
        prefix = "<" if byteorder.upper().startswith("LSB") else ">"
        payload = codes.astype(np.dtype(prefix + "u2")).tobytes()
    else:
        raise ValueError(f"encode handles BYTE/WORD only, not format {pre.fmt}")

    length = len(payload)
    digits = str(length)
    header = f"#{len(digits)}{digits}".encode("ascii")
    return header + payload
