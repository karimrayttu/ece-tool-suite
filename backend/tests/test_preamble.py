"""Spike C: prove the Keysight preamble math + the sim/real shared decode path.

We build a known sine in volts, encode it to a raw block using a preamble (as the
SimTransport would), then decode it back — and assert we recover the sine within one
quantization step. This is the exact code path a real :WAVeform:DATA? block would take.
"""

import numpy as np

from ece_suite.instruments.preamble import (
    FORMAT_BYTE,
    FORMAT_WORD,
    Preamble,
    decode_waveform,
    encode_waveform_block,
    parse_definite_length_block,
    parse_preamble,
)


def test_parse_preamble_fields():
    # format=1(WORD), type=2(AVER), points=1000, count=8, then x/y scaling
    s = "+1,+2,+1000,+8,+1.000000E-09,-5.000000E-07,+0,+3.750000E-04,+0.000000E+00,+32768"
    pre = parse_preamble(s)
    assert pre.fmt == FORMAT_WORD
    assert pre.points == 1000
    assert pre.count == 8
    assert pre.xincrement == 1e-9
    assert pre.xorigin == -5e-7
    assert pre.yincrement == 3.75e-4
    assert pre.yreference == 32768


def test_parse_definite_length_block():
    payload = bytes(range(10))
    block = b"#2" + b"10" + payload  # #210<10 bytes>
    assert parse_definite_length_block(block) == payload
    # tolerate leading/trailing whitespace and newline terminator
    assert parse_definite_length_block(b"\n" + block + b"\n") == payload


def test_time_axis_scaling_byte():
    pre = Preamble(
        fmt=FORMAT_BYTE, wtype=0, points=5, count=1,
        xincrement=2e-9, xorigin=-4e-9, xreference=0,
        yincrement=1.0, yorigin=0.0, yreference=128,
    )
    block = encode_waveform_block(np.zeros(5), pre)
    t, _v = decode_waveform(block, pre)
    np.testing.assert_allclose(t, [-4e-9, -2e-9, 0.0, 2e-9, 4e-9], rtol=0, atol=1e-18)


def test_roundtrip_sine_word_within_one_lsb():
    # 16-bit WORD format, +/-1 V full-ish scale centered at code 32768
    n = 1000
    yinc = 2.0 / 60000.0  # ~ volts per code
    pre = Preamble(
        fmt=FORMAT_WORD, wtype=0, points=n, count=1,
        xincrement=1e-9, xorigin=0.0, xreference=0,
        yincrement=yinc, yorigin=0.0, yreference=32768,
    )
    t_in = np.arange(n) * pre.xincrement
    v_in = 0.9 * np.sin(2 * np.pi * 1e6 * t_in)  # 1 MHz, 0.9 Vpk

    block = encode_waveform_block(v_in, pre, byteorder="LSB")
    t_out, v_out = decode_waveform(block, pre, byteorder="LSB")

    assert t_out.shape == v_out.shape == (n,)
    np.testing.assert_allclose(t_out, t_in, rtol=0, atol=1e-18)
    # recovered volts within one quantization step
    np.testing.assert_allclose(v_out, v_in, atol=yinc * 1.001)


def test_roundtrip_byte_format():
    n = 256
    pre = Preamble(
        fmt=FORMAT_BYTE, wtype=0, points=n, count=1,
        xincrement=1e-6, xorigin=0.0, xreference=0,
        yincrement=8.0 / 256.0, yorigin=0.0, yreference=128,  # +/-4 V over 8 bits
    )
    v_in = np.linspace(-3.5, 3.5, n)
    block = encode_waveform_block(v_in, pre)
    _t, v_out = decode_waveform(block, pre)
    np.testing.assert_allclose(v_out, v_in, atol=pre.yincrement * 1.001)
