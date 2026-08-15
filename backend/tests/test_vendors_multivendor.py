"""Multi-vendor wiring: vendor detection, Tektronix scope driver, Fluke 28x handheld,
and the connect-by-address resource builder."""

from __future__ import annotations

import numpy as np
import pytest

from ece_suite.instruments.dmm import Fluke28xDmm, make_dmm
from ece_suite.instruments.scope_drivers import (
    KeysightScope,
    TektronixScope,
    _parse_ieee_block,
    make_scope,
)
from ece_suite.instruments.transport import Transport
from ece_suite.instruments.vendors import canonical_vendor, scope_dialect
from ece_suite.main import build_visa_resource
from ece_suite.provenance import Provenance


class FakeInstrument(Transport):
    default_provenance = Provenance.UNVERIFIED_HW

    def __init__(self, answers: dict[str, str], raw: bytes = b"", *, fail_idn: bool = False):
        self.answers = answers
        self.raw = raw
        self.fail_idn = fail_idn
        self.writes: list[str] = []

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        c = cmd.strip()
        if c == "*IDN?" and self.fail_idn:
            raise RuntimeError("no response")
        return self.answers.get(c, "0")

    def query_raw(self, cmd: str) -> bytes:
        return self.raw


@pytest.mark.parametrize("field,expected", [
    ("KEYSIGHT TECHNOLOGIES", "keysight"), ("AGILENT", "keysight"),
    ("RIGOL TECHNOLOGIES", "rigol"), ("SIGLENT", "siglent"),
    ("TEKTRONIX", "tektronix"), ("FLUKE", "fluke"),
    ("ROHDE&SCHWARZ", "rohde"), ("GW INSTEK", "gwinstek"), ("Nobody", "unknown"),
])
def test_vendor_detection(field, expected):
    assert canonical_vendor(field) == expected


def test_scope_dialect_only_tek_diverges():
    assert scope_dialect("tektronix") == "tektronix"
    for v in ("keysight", "rigol", "siglent", "rohde", "unknown"):
        assert scope_dialect(v) == "keysight"


def test_make_scope_picks_keysight_for_rigol():
    t = FakeInstrument({"*IDN?": "RIGOL TECHNOLOGIES,DS1054Z,DS1ZA,00.04"})
    assert isinstance(make_scope(t), KeysightScope)
    assert not isinstance(make_scope(t), TektronixScope)


def test_make_scope_picks_tektronix():
    codes = np.round(1000 * np.sin(np.linspace(0, 6.28, 40))).astype(">i2").tobytes()
    n = len(codes)
    block = f"#{len(str(n))}{n}".encode() + codes
    t = FakeInstrument({
        "*IDN?": "TEKTRONIX,MSO54,C0123,1.0",
        "WFMOutpre:XINCR?": "1e-6", "WFMOutpre:XZEro?": "0", "WFMOutpre:YMUlt?": "1e-3",
        "WFMOutpre:YOFf?": "0", "WFMOutpre:YZEro?": "0", "SELect:CH1?": "1",
        "MEASUrement:IMMed:VALue?": "2.0",
    }, raw=block)
    drv = make_scope(t)
    assert isinstance(drv, TektronixScope)
    wf = drv.capture(1)
    assert len(wf.v) == 40
    assert drv.measure_all(1)["vpp"]["value"] == 2.0


def test_parse_ieee_block():
    assert _parse_ieee_block(b"#14ABCD") == b"ABCD"
    assert _parse_ieee_block(b"#210" + b"x" * 10) == b"x" * 10
    assert _parse_ieee_block(b"raw") == b"raw"


def test_fluke_28x_detected_when_idn_silent():
    t = FakeInstrument({"ID": "FLUKE 287,V1.10,8899", "QM": "QM,+1.23456E+0,VDC,NORMAL,NONE"},
                       fail_idn=True)
    drv = make_dmm(t)
    assert isinstance(drv, Fluke28xDmm)
    r = drv.read()
    assert r["value"] == pytest.approx(1.23456)
    assert r["unit"] == "V" and r["dialect"] == "fluke-28x"


def test_build_visa_resource():
    assert build_visa_resource("192.168.0.10", "lan") == "TCPIP0::192.168.0.10::inst0::INSTR"
    assert build_visa_resource("192.168.0.10", "socket") == "TCPIP0::192.168.0.10::5025::SOCKET"
    assert build_visa_resource("192.168.0.10", "socket", 5030) == "TCPIP0::192.168.0.10::5030::SOCKET"
    assert build_visa_resource("COM3", "serial") == "ASRL3::INSTR"
    assert build_visa_resource("22", "gpib") == "GPIB0::22::INSTR"


# --- regression: verification-workflow findings -------------------------------
def test_make_scope_does_not_cache_on_failed_idn():
    """A momentarily-unreachable scope must not be permanently locked to a dialect."""
    t = FakeInstrument({}, fail_idn=True)
    make_scope(t)                         # *IDN? fails -> vendor unknown
    assert not hasattr(t, "_scope_dialect")  # not cached; can re-detect next call


def test_tektronix_capture_sets_data_stop():
    import numpy as np
    codes = np.round(1000 * np.sin(np.linspace(0, 6.28, 40))).astype(">i2").tobytes()
    block = f"#{len(str(len(codes)))}{len(codes)}".encode() + codes
    t = FakeInstrument({
        "*IDN?": "TEKTRONIX,MSO54,C0,1.0", "HORizontal:RECOrdlength?": "40",
        "WFMOutpre:XINCR?": "1e-6", "WFMOutpre:YMUlt?": "1e-3", "SELect:CH1?": "1",
    }, raw=block)
    drv = make_scope(t)
    drv.capture(1)
    assert any(w.startswith("DATa:STOP") for w in t.writes), "must set DATa:STOP for full record"


def test_visa_transport_has_io_lock():
    import inspect

    from ece_suite.instruments.transport import VisaTransport
    src = inspect.getsource(VisaTransport)
    assert "_io_lock" in src and "with self._io_lock" in src
