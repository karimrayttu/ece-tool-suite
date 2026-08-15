"""Common SCPI machinery for simulated instruments.

Handles the IEEE-488.2 mandatory commands (*IDN?, *RST, *CLS, :SYST:ERR?) and an error
queue; device models override the ``_handle_*`` hooks. Implements the ``Transport``
interface so a sim instrument is a drop-in for a real one.
"""

from __future__ import annotations

from ...provenance import Provenance
from ..transport import Transport


class SimInstrument(Transport):
    default_provenance = Provenance.SIMULATED
    idn = "SIM,GENERIC,SN-0000,0.0.0"

    def __init__(self) -> None:
        self._errq: list[str] = []

    # -- error queue (used by safety + fault injection) -------------------
    def inject_error(self, msg: str) -> None:
        """Queue a SCPI error so :SYST:ERR? reports it once."""
        self._errq.append(msg)

    # -- Transport interface ---------------------------------------------
    def write(self, cmd: str) -> None:
        c = cmd.strip()
        u = c.upper()
        if u == "*CLS":
            self._errq.clear()
            return
        if u == "*RST":
            self._errq.clear()
            self._on_reset()
            return
        try:
            self._handle_write(c, u)
        except (ValueError, IndexError):
            self._errq.append('-113,"Undefined header"')

    def query(self, cmd: str) -> str:
        c = cmd.strip()
        u = c.upper()
        if u == "*IDN?":
            return self.idn
        if u in (":SYST:ERR?", ":SYSTEM:ERROR?"):
            return self._errq.pop(0) if self._errq else '+0,"No error"'
        out = self._handle_query(c, u)
        return out if out is not None else ""

    def query_raw(self, cmd: str) -> bytes:
        c = cmd.strip()
        u = c.upper()
        out = self._handle_query_raw(c, u)
        return out if out is not None else b""

    # -- hooks for device models -----------------------------------------
    def _on_reset(self) -> None:
        pass

    def _handle_write(self, cmd: str, upper: str) -> None:
        """Override. Unknown writes are accepted silently, like a lenient instrument."""

    def _handle_query(self, cmd: str, upper: str) -> str | None:
        return None

    def _handle_query_raw(self, cmd: str, upper: str) -> bytes | None:
        return None
