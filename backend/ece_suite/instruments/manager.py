"""Instrument manager: owns the active transport per role and swaps sim <-> real.

Single source of truth for "what is currently behind 'scope'": a SimScope by default, or a
VisaTransport once connected. Each VisaTransport serializes its own I/O with an internal lock,
so concurrent callers (a WS stream + the chatbox/agent) cannot interleave writes/reads on the
same instrument handle. The manager runs the verification gate; disconnecting reverts the role
to a fresh simulator.
"""

from __future__ import annotations

from collections.abc import Callable

from ..provenance import Provenance
from ..verification import VerificationGate, VerifyResult
from .transport import Transport, VisaTransport


class InstrumentManager:
    def __init__(self, roles: dict[str, Transport], *, gate: VerificationGate | None = None, audit=None):
        self._roles: dict[str, Transport] = dict(roles)
        self._sim_factories: dict[str, Callable[[], Transport]] = {}
        self.gate = gate or VerificationGate(audit=audit)
        self.audit = audit

    def register_sim_factory(self, role: str, factory: Callable[[], Transport]) -> None:
        self._sim_factories[role] = factory

    def roles(self) -> dict[str, Transport]:
        return dict(self._roles)

    def get(self, role: str) -> Transport | None:
        return self._roles.get(role)

    def connected(self, role: str) -> bool:
        return self._roles.get(role) is not None

    def set(self, role: str, transport: Transport) -> None:
        self._roles[role] = transport

    def connect_visa(self, role: str, resource: str, **kw) -> VisaTransport:
        t = VisaTransport(resource, **kw)
        old = self._roles.get(role)
        if isinstance(old, VisaTransport):
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        self._roles[role] = t
        if self.audit is not None:
            self.audit.record("instrument_connect", role=role, resource=resource)
        return t

    def disconnect(self, role: str) -> None:
        old = self._roles.get(role)
        if isinstance(old, VisaTransport):
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        factory = self._sim_factories.get(role)
        self._roles[role] = factory() if factory is not None else None
        if self.audit is not None:
            self.audit.record("instrument_disconnect", role=role)

    def verify(self, role: str) -> VerifyResult:
        return self.gate.verify(self._roles[role], role=role)

    def has_exclusive(self, role: str) -> bool:
        """Whether writes to this role are serialized (a precondition for source ops).

        True whenever the role is connected: a VisaTransport serializes its own I/O with an
        internal lock (see transport.py), and a simulator is exclusively ours. This is a
        single-process app, so no other process shares the instrument handle.
        """
        return self._roles.get(role) is not None

    def status(self) -> dict:
        out: dict[str, dict] = {}
        for role, t in self._roles.items():
            if t is None:
                out[role] = {"connected": False, "backend": None, "provenance": None, "resource": None}
                continue
            d = {"connected": True, "backend": type(t).__name__, "provenance": t.default_provenance.value}
            d["resource"] = t.resource if isinstance(t, VisaTransport) else None
            d["vendor"] = getattr(t, "_vendor", None)
            out[role] = d
        return out

    def any_hardware_verified(self) -> bool:
        return any(t is not None and t.default_provenance is Provenance.VERIFIED_HW
                   for t in self._roles.values())

    def any_connected(self) -> bool:
        return any(t is not None for t in self._roles.values())
