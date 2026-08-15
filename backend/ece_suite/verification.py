"""The lab-truth gate.

A connection may only be labeled VERIFIED_HW after a live instrument acknowledges `*IDN?`
AND a read-back check passes (here: the `:SYST:ERR?` queue drains empty). A SIMULATED
transport is NEVER promotable — that is the whole point of the honesty contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from .instruments.scpi import IdnInfo, drain_error_queue, parse_idn
from .instruments.transport import Transport
from .provenance import Provenance


@dataclass
class VerifyResult:
    ok: bool
    provenance: str
    idn: IdnInfo | None
    reasons: list[str]


class VerificationGate:
    def __init__(self, audit=None):
        self.audit = audit

    def verify(self, transport: Transport, *, role: str = "?") -> VerifyResult:
        reasons: list[str] = []
        is_hardware = transport.default_provenance is not Provenance.SIMULATED

        idn: IdnInfo | None = None
        try:
            raw = transport.query("*IDN?")
            idn = parse_idn(raw)
            if not idn.vendor or not idn.model:
                reasons.append("*IDN? response incomplete (missing vendor/model)")
        except Exception as e:  # noqa: BLE001
            reasons.append(f"*IDN? failed: {e}")

        # read-back: the error queue must drain empty
        try:
            errs = drain_error_queue(transport)
            if errs:
                reasons.append(f"instrument error queue not empty: {errs}")
        except Exception as e:  # noqa: BLE001
            reasons.append(f"error-queue read-back failed: {e}")

        if not is_hardware:
            reasons.append("transport is SIMULATED — a simulator can never be VERIFIED_HW")

        ok = is_hardware and not reasons
        if ok:
            promote = getattr(transport, "promote_to_verified", None)
            if callable(promote):
                promote()
            else:  # any hardware transport exposing a settable provenance
                transport.default_provenance = Provenance.VERIFIED_HW
            prov = Provenance.VERIFIED_HW
            reasons = ["verified: *IDN? acknowledged and read-back clean"]
        else:
            prov = transport.default_provenance

        if self.audit is not None:
            self.audit.record(
                "verify_gate", role=role, ok=ok, provenance=prov.value,
                idn=(idn.raw if idn else None), reasons=reasons,
            )
        return VerifyResult(ok=ok, provenance=prov.value, idn=idn, reasons=reasons)
