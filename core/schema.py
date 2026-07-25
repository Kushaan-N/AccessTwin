"""Access-Twin core data schema. Single source of truth for agent
parameters and the audit result contract."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

IN_PER_M = 39.3701


class ViolationType(str, Enum):
    CLEARANCE = "clearance_width"
    SLOPE = "slope_gradient"
    TURNING_RADIUS = "turning_radius"
    HEAD_CLEARANCE = "head_clearance"
    STEP_HEIGHT = "step_height"
    UNREACHABLE = "unreachable_region"


class Severity(str, Enum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"; CRITICAL = "critical"


@dataclass
class MobilityAgentProfile:
    """Physics envelope for a simulated mobility agent. Inches."""
    name: str
    width_in: float
    turning_radius_in: float
    max_slope_ratio: float           # rise/run, e.g. 1/12 = 0.0833
    max_step_in: float = 0.5
    head_clearance_in: Optional[float] = None
    cane_sweep_arc_in: Optional[float] = None

    @property
    def required_clearance_in(self) -> float:
        # ADA convention: wider of body width vs. sweep arc.
        return max(self.cane_sweep_arc_in or 0.0, self.width_in)

    # --- metric accessors used by the nav grid ---
    @property
    def radius_m(self) -> float:
        return (self.required_clearance_in / 2.0) / IN_PER_M

    @property
    def max_step_m(self) -> float:
        return self.max_step_in / IN_PER_M

    @property
    def turning_radius_m(self) -> float:
        return self.turning_radius_in / IN_PER_M


WHEELCHAIR = MobilityAgentProfile(
    name="wheelchair", width_in=32.0, turning_radius_in=60.0,
    max_slope_ratio=1 / 12, max_step_in=0.5)
CANE_SWEEP = MobilityAgentProfile(
    name="vision_impaired_cane", width_in=24.0, turning_radius_in=36.0,
    max_slope_ratio=1 / 10, max_step_in=6.0,
    head_clearance_in=80.0, cane_sweep_arc_in=42.0)
BASELINE = MobilityAgentProfile(
    name="baseline_walking", width_in=20.0, turning_radius_in=18.0,
    max_slope_ratio=1 / 4, max_step_in=16.0)
DELIVERY_ROBOT = MobilityAgentProfile(
    name="sidewalk_delivery_robot", width_in=26.0, turning_radius_in=30.0,
    max_slope_ratio=1 / 8, max_step_in=2.0)

ALL_PROFILES = [BASELINE, WHEELCHAIR, CANE_SWEEP, DELIVERY_ROBOT]

ADA_CITATIONS = {
    ViolationType.CLEARANCE: "ADA 2010 §404.2.3 / §403.5.1 — clear width",
    ViolationType.SLOPE: "ADA 2010 §405.2 — ramp running slope max 1:12",
    ViolationType.TURNING_RADIUS: "ADA 2010 §304.3.1 — 60in turning space",
    ViolationType.STEP_HEIGHT: "ADA 2010 §303.2 — changes in level max 1/2in",
    ViolationType.HEAD_CLEARANCE: "ADA 2010 §307.4 — 80in vertical clearance",
    ViolationType.UNREACHABLE: "Derived — connectivity, no direct ADA analogue",
}


@dataclass
class TelemetryPoint:
    t: float; x: float; y: float; z: float
    heading_deg: float; velocity_mps: float
    hesitation_score: float = 0.0     # 0-1 dwell/backtrack signal
    interaction_trigger: Optional[str] = None


@dataclass
class EnvironmentSegment:
    segment_id: str
    start_xyz: tuple[float, float, float]
    end_xyz: tuple[float, float, float]
    clearance_width_in: float
    slope_ratio: float
    ceiling_height_in: float = 96.0
    step_height_in: float = 0.0


@dataclass
class ViolationNode:
    segment_id: str
    position: tuple[float, float, float]
    violation_type: ViolationType
    agent: str
    measured_value: float
    threshold: float
    severity: Severity
    hesitation_context: float = 0.0
    confirmed_by: list[str] = field(default_factory=list)
    ada_citation: str = ""

    @property
    def consensus(self) -> int:
        return len(self.confirmed_by)


@dataclass
class AuditResult:
    violations: list[ViolationNode] = field(default_factory=list)
    segments_checked: int = 0
    agents_evaluated: list[str] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    islands: dict = field(default_factory=dict)
    ground_truth: dict = field(default_factory=dict)
    recall: dict = field(default_factory=dict)
    seed: int = 0

    def to_json(self) -> dict:
        return {
            "seed": self.seed,
            "segments_checked": self.segments_checked,
            "agents_evaluated": self.agents_evaluated,
            "violation_count": len(self.violations),
            "coverage": self.coverage,
            "islands": self.islands,
            "ground_truth": self.ground_truth,
            "recall": self.recall,
            "violations": [
                {
                    "segment_id": v.segment_id,
                    "position": v.position,
                    "type": v.violation_type.value,
                    "agent": v.agent,
                    "measured": round(v.measured_value, 2),
                    "threshold": round(v.threshold, 2),
                    "severity": v.severity.value,
                    "hesitation_context": round(v.hesitation_context, 2),
                    "confirmed_by": v.confirmed_by,
                    "consensus": v.consensus,
                    "ada_citation": v.ada_citation,
                }
                for v in self.violations
            ],
        }
