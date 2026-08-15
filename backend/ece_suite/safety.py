"""Safety invariant engine.

Evaluates a proposed instrument action and returns ALLOW / REQUIRE_CONFIRM / BLOCK with
cited reasons. Combination rule: most-restrictive-wins.

This engine is a *secondary* guard. The PLAN's discipline is explicit: the instrument's own
hardware-configured limits (OVP/OCP, front-end absolute-maximum for the live coupling /
attenuation / impedance) are the real safety mechanism. This engine refuses to let software
*pretend* to be that mechanism — e.g. it forbids native AUToscale, demands a declared DUT
envelope before any source op, and (via the PresetRunner) requires protective limits to be
set and verified before an output is ever enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .registry import Capability


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_CONFIRM = "REQUIRE_CONFIRM"
    BLOCK = "BLOCK"

    @property
    def rank(self) -> int:
        return {"ALLOW": 0, "REQUIRE_CONFIRM": 1, "BLOCK": 2}[self.value]


class OpType(str, Enum):
    READ = "READ"
    CONFIGURE = "CONFIGURE"
    SET_LEVEL = "SET_LEVEL"            # set source output level (V/I)
    SET_PROTECTION = "SET_PROTECTION"  # set OVP/OCP
    ENABLE_OUTPUT = "ENABLE_OUTPUT"
    DISABLE_OUTPUT = "DISABLE_OUTPUT"
    AUTOSCALE = "AUTOSCALE"


@dataclass(frozen=True)
class DUTSafetyEnvelope:
    """The declared safe operating area of the device under test. Required before any
    source/load operation — there is no safe default, so its absence is default-deny."""

    max_voltage: float
    max_current: float
    min_current: float = 0.0
    polarity: str = "positive"   # positive | negative | bipolar


@dataclass(frozen=True)
class RatingModel:
    """Instrument absolute limits (mirrors the datasheet / front-panel rating)."""

    max_output_voltage: float | None = None
    max_output_current: float | None = None
    input_abs_max_voltage: float | None = None


@dataclass(frozen=True)
class ScopeFrontEnd:
    """Live-queried front-end state — all three are needed to compute abs-max."""

    attenuation: float = 1.0
    coupling: str = "DC"
    input_impedance: float = 1e6


def effective_abs_max_v(fe: ScopeFrontEnd, *, base_1m_abs_max: float = 300.0,
                        fifty_ohm_abs_max: float = 5.0) -> float:
    """Effective front-end absolute-max input, reconciled from impedance, coupling and
    probe attenuation. At 50 Ω the front end is power-limited to a low abs-max; at 1 MΩ it
    is higher; a 10x probe raises the measurable ceiling proportionally."""
    base = fifty_ohm_abs_max if fe.input_impedance <= 100 else base_1m_abs_max
    return base * max(fe.attenuation, 1.0)


@dataclass(frozen=True)
class Action:
    capability: Capability
    op: OpType
    instrument: str
    params: dict = field(default_factory=dict)
    raw_scpi: str | None = None


@dataclass(frozen=True)
class SafetyDecision:
    verdict: Verdict
    reasons: list[str]

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def blocked(self) -> bool:
        return self.verdict is Verdict.BLOCK

    @property
    def needs_confirm(self) -> bool:
        return self.verdict is Verdict.REQUIRE_CONFIRM


class SafetyInvariantEngine:
    def evaluate(
        self,
        action: Action,
        *,
        envelope: DUTSafetyEnvelope | None = None,
        rating: RatingModel | None = None,
        scope_front_end: ScopeFrontEnd | None = None,
    ) -> SafetyDecision:
        findings: list[tuple[Verdict, str]] = []

        # 1) Native AUToscale is forbidden in any automated path.
        raw = (action.raw_scpi or "").upper()
        if action.op is OpType.AUTOSCALE or "AUTOSC" in raw or raw.strip() in (":AUT", ":AUTOSCALE"):
            findings.append((Verdict.BLOCK,
                "native :AUToScale is forbidden in presets; use app-computed bounded "
                ":RANGe/:SCALe/:OFFSet with a verify-read"))

        is_source = action.capability is Capability.SOURCE_CONTROL

        # 2) Default-deny: any source op needs a declared DUT envelope.
        if is_source and action.op in (OpType.SET_LEVEL, OpType.ENABLE_OUTPUT):
            if envelope is None:
                findings.append((Verdict.BLOCK,
                    "SOURCE_CONTROL is default-denied until a DUT SafetyEnvelope is declared"))

        # 3) Set-level must be within BOTH the DUT envelope and the instrument rating.
        if is_source and action.op is OpType.SET_LEVEL:
            v = action.params.get("voltage")
            i = action.params.get("current")
            if v is not None and envelope is not None:
                if v > envelope.max_voltage:
                    findings.append((Verdict.BLOCK,
                        f"voltage {v} V exceeds DUT envelope max {envelope.max_voltage} V"))
                if envelope.polarity == "positive" and v < 0:
                    findings.append((Verdict.BLOCK, "negative voltage violates DUT polarity (positive)"))
            if v is not None and rating is not None and rating.max_output_voltage is not None:
                if v > rating.max_output_voltage:
                    findings.append((Verdict.BLOCK,
                        f"voltage {v} V exceeds instrument rating {rating.max_output_voltage} V"))
            if i is not None and envelope is not None and i > envelope.max_current:
                findings.append((Verdict.BLOCK,
                    f"current {i} A exceeds DUT envelope max {envelope.max_current} A"))
            if i is not None and rating is not None and rating.max_output_current is not None:
                if i > rating.max_output_current:
                    findings.append((Verdict.BLOCK,
                        f"current {i} A exceeds instrument rating {rating.max_output_current} A"))

        # 4) Enabling an output energizes the DUT -> always needs explicit human confirm.
        if is_source and action.op is OpType.ENABLE_OUTPUT:
            findings.append((Verdict.REQUIRE_CONFIRM,
                "enabling an output energizes the DUT; explicit human confirmation required"))

        # 5) Scope near-limit configuration must respect the live effective abs-max.
        if action.op in (OpType.CONFIGURE, OpType.SET_LEVEL) and scope_front_end is not None:
            expected = action.params.get("expected_input_v")
            if expected is not None:
                limit = effective_abs_max_v(scope_front_end)
                if abs(expected) > limit:
                    findings.append((Verdict.BLOCK,
                        f"expected input {expected} V exceeds effective front-end abs-max "
                        f"{limit:.1f} V (Z={scope_front_end.input_impedance:g}, "
                        f"atten={scope_front_end.attenuation:g}x, coup={scope_front_end.coupling})"))

        if not findings:
            return SafetyDecision(Verdict.ALLOW, ["no invariant triggered"])
        worst = max((f[0] for f in findings), key=lambda v: v.rank)
        # order reasons worst-first
        reasons = [r for v, r in sorted(findings, key=lambda f: -f[0].rank)]
        return SafetyDecision(worst, reasons)
