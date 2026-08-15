"""Round-trip tests for the logic-analyzer decoders: generate a known waveform, decode it,
and check the bytes come back."""

from __future__ import annotations

import pytest

from ece_suite import logic_decode as L


@pytest.mark.parametrize("msg,baud", [("Hi!", 9600), ("Extract", 115200), ("A", 921600)])
def test_uart_roundtrip(msg, baud):
    sr = max(4_000_000, baud * 20)  # keep >=20x oversampling, as a real analyzer would
    cap = L.gen_uart([ord(c) for c in msg], baud=baud, sample_rate=sr)
    got = L.decode_uart(cap["channels"]["RX"], cap["sample_rate"], baud)
    assert "".join(chr(d["value"]) for d in got) == msg
    assert all(not d["parity_error"] and not d["framing_error"] for d in got)


@pytest.mark.parametrize("cpol,cpha", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_spi_all_modes(cpol, cpha):
    data = [0x9F, 0xEF, 0x40, 0x18]
    cap = L.gen_spi(data, cpol=cpol, cpha=cpha)
    got = L.decode_spi(cap["channels"]["CLK"], cap["channels"]["MOSI"], None,
                       cap["channels"]["CS"], cap["sample_rate"], cpol=cpol, cpha=cpha)
    assert [d["mosi"] for d in got] == data


def test_spi_lsb_first():
    cap = L.gen_spi([0x01], cpol=0, cpha=0)  # MSB-first generator
    got = L.decode_spi(cap["channels"]["CLK"], cap["channels"]["MOSI"], None,
                       cap["channels"]["CS"], cap["sample_rate"], bitorder="lsb")
    assert got[0]["mosi"] == 0x80  # 0x01 read LSB-first -> 0x80


def test_i2c_write():
    cap = L.gen_i2c(0x50, [0x00, 0x48, 0x69], read=False)
    ev = L.decode_i2c(cap["channels"]["SCL"], cap["channels"]["SDA"], cap["sample_rate"])
    types = [e["type"] for e in ev]
    assert types[0] == "start" and types[-1] == "stop"
    addr = next(e for e in ev if e["type"] == "address")
    assert addr["value"] == 0x50 and addr["rw"] == "write" and addr["ack"]
    data = [e["value"] for e in ev if e["type"] == "data"]
    assert data == [0x00, 0x48, 0x69]


def test_i2c_read_flag():
    cap = L.gen_i2c(0x3C, [0xFF], read=True)
    ev = L.decode_i2c(cap["channels"]["SCL"], cap["channels"]["SDA"], cap["sample_rate"])
    addr = next(e for e in ev if e["type"] == "address")
    assert addr["value"] == 0x3C and addr["rw"] == "read"


def test_sample_capture_shapes():
    for proto in ("spi", "i2c", "uart"):
        cap = L.sample_capture(proto)
        assert cap["protocol"] == proto
        assert cap["channels"] and "mapping" in cap
        # every channel is a 0/1 list of equal length
        lens = {len(v) for v in cap["channels"].values()}
        assert len(lens) == 1
        assert all(set(v) <= {0, 1} for v in cap["channels"].values())
