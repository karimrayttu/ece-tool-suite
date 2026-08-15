"""Transactional preset runner.

A preset is an ordered list of :class:`PresetStep`. The runner enforces the source-safety
ordering *before executing anything*:

* an ``ENABLE_OUTPUT`` step, if present, MUST be the last step;
* protective limits (OVP/OCP via ``SET_PROTECTION``) MUST be set+verified before enable.

During execution every step is gated by the :class:`SafetyInvariantEngine`, each write's
``:SYST:ERR?`` queue must drain empty (post-condition), and configurable steps are
verify-read. Any failure aborts and rolls back — and the FIRST rollback action is always an
unconditional output-off.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .instruments.scpi import drain_error_queue
from .instruments.transport import Transport
from .registry import Capability
from .safety import (
    Action,
    DUTSafetyEnvelope,
    OpType,
    RatingModel,
    SafetyInvariantEngine,
    ScopeFrontEnd,
)


@dataclass
class PresetStep:
    op: OpType
    scpi: str
    capability: Capability = Capability.CONFIGURE_INSTRUMENT
    params: dict = field(default_factory=dict)
    verify_query: str | None = None
    expected: float | None = None
    tol: float = 1e-6
    description: str = ""


@dataclass
class StepResult:
    description: str
    verdict: str
    executed: bool
    verified: bool
    error: str | None = None


@dataclass
class PresetResult:
    ok: bool
    provenance: str
    steps: list[StepResult]
    rolled_back: bool
    summary: str


class PresetRunner:
    def __init__(
        self,
        transport: Transport,
        engine: SafetyInvariantEngine | None = None,
        *,
        instrument: str = "PSU",
        audit=None,
        output_off_scpi: str = ":OUTP OFF",
    ):
        self.t = transport
        self.engine = engine or SafetyInvariantEngine()
        self.instrument = instrument
        self.audit = audit
        self.output_off_scpi = output_off_scpi

    def _validate_ordering(self, steps: list[PresetStep]) -> str | None:
        enable_idx = [i for i, s in enumerate(steps) if s.op is OpType.ENABLE_OUTPUT]
        if len(enable_idx) > 1:
            return "more than one ENABLE_OUTPUT step in a preset"
        if enable_idx:
            ei = enable_idx[0]
            if ei != len(steps) - 1:
                return "ENABLE_OUTPUT must be the last step"
            if not any(s.op is OpType.SET_PROTECTION for s in steps[:ei]):
                return "output enable requires protective limits (OVP/OCP) set+verified beforehand"
        return None

    def _audit(self, event: str, **kw) -> None:
        if self.audit is not None:
            self.audit.record(event, **kw)

    def _abort(self, results: list[StepResult], prov: str, *, reason: str) -> PresetResult:
        # rollback: unconditional output-off FIRST, no matter what
        try:
            self.t.write(self.output_off_scpi)
            drain_error_queue(self.t)
        except Exception:  # noqa: BLE001 - rollback must never raise
            pass
        self._audit("preset_rollback", instrument=self.instrument, reason=reason)
        return PresetResult(False, prov, results, True, f"ABORTED + rolled back: {reason}")

    def run(
        self,
        steps: list[PresetStep],
        *,
        envelope: DUTSafetyEnvelope | None = None,
        rating: RatingModel | None = None,
        scope_front_end: ScopeFrontEnd | None = None,
        confirm: bool = False,
    ) -> PresetResult:
        prov = self.t.default_provenance.value
        results: list[StepResult] = []

        order_err = self._validate_ordering(steps)
        if order_err:
            self._audit("preset_blocked_ordering", instrument=self.instrument, reason=order_err)
            results.append(StepResult("ordering check", "BLOCK", False, False, order_err))
            return PresetResult(False, prov, results, False, f"BLOCKED (ordering): {order_err}")

        for s in steps:
            action = Action(s.capability, s.op, self.instrument, s.params, s.scpi)
            decision = self.engine.evaluate(
                action, envelope=envelope, rating=rating, scope_front_end=scope_front_end
            )
            if decision.blocked:
                reason = "; ".join(decision.reasons)
                results.append(StepResult(s.description or s.scpi, "BLOCK", False, False, reason))
                return self._abort(results, prov, reason=reason)
            if decision.needs_confirm and not confirm:
                results.append(StepResult(s.description or s.scpi, "REQUIRE_CONFIRM", False, False,
                                          "human confirmation required but not provided"))
                return self._abort(results, prov, reason="confirmation required but not provided")

            self.t.write(s.scpi)

            # post-condition: error queue must be empty after a safety-relevant write
            errs = drain_error_queue(self.t)
            if errs:
                results.append(StepResult(s.description or s.scpi, decision.verdict.value, True, False,
                                          f":SYST:ERR not empty: {errs}"))
                return self._abort(results, prov, reason=f"instrument error after write: {errs}")

            verified = True
            if s.verify_query is not None and s.expected is not None:
                got = self.t.query(s.verify_query)
                try:
                    verified = abs(float(got) - s.expected) <= s.tol
                except ValueError:
                    verified = False
                if not verified:
                    results.append(StepResult(s.description or s.scpi, decision.verdict.value, True, False,
                                              f"verify mismatch: got {got!r}, expected {s.expected}"))
                    return self._abort(results, prov, reason="verify-read mismatch")

            results.append(StepResult(s.description or s.scpi, decision.verdict.value, True, verified, None))

        self._audit("preset_complete", instrument=self.instrument, steps=len(steps), provenance=prov)
        return PresetResult(True, prov, results, False, "preset completed")

    def preview(
        self,
        steps: list[PresetStep],
        *,
        envelope: DUTSafetyEnvelope | None = None,
        rating: RatingModel | None = None,
        scope_front_end: ScopeFrontEnd | None = None,
    ) -> dict:
        """Dry-run: evaluate ordering + per-step safety verdicts WITHOUT executing anything.
        The UI uses this to show ALLOW / REQUIRE_CONFIRM / BLOCK on a preset card before run."""
        order_err = self._validate_ordering(steps)
        if order_err:
            return {
                "ok_to_run": False,
                "overall": "BLOCK",
                "ordering_error": order_err,
                "provenance": self.t.default_provenance.value,
                "steps": [],
            }
        step_views: list[dict] = []
        worst_rank = 0
        for s in steps:
            action = Action(s.capability, s.op, self.instrument, s.params, s.scpi)
            d = self.engine.evaluate(action, envelope=envelope, rating=rating, scope_front_end=scope_front_end)
            worst_rank = max(worst_rank, d.verdict.rank)
            step_views.append({"description": s.description or s.scpi, "verdict": d.verdict.value, "reasons": d.reasons})
        overall = ["ALLOW", "REQUIRE_CONFIRM", "BLOCK"][worst_rank]
        return {
            "ok_to_run": overall != "BLOCK",
            "overall": overall,
            "ordering_error": None,
            "provenance": self.t.default_provenance.value,
            "steps": step_views,
        }
