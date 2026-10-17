"""
Level 3 — Decision package and course-of-action card.

The operator receives a structured ``DecisionPackage`` rather than an opaque
score.  It contains all the distinct views listed in structure.md:

    Current situation · Predictive view · Authorization view
    Behaviour insights · Evidence quality · Recommended next action
    Reason and alternatives · Human handoff package

A ``CourseOfActionCard`` is the shareable one-record summary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from simulator.engine.incident.incident_fsm import Incident, IncidentState
from simulator.engine.planner.action_planner import ActionID, ActionPlan
from simulator.engine.policy.policy_engine import AuthorizationVerdict, PolicyResult
from simulator.engine.predictor.trajectory_predictor import TrajectoryForecast
from simulator.engine.tracker.kalman_tracker import TrackState


# ---------------------------------------------------------------------------
# Sub-sections
# ---------------------------------------------------------------------------

@dataclass
class SituationView:
    """Current track location, movement, identity status, last observation."""
    track_id:            str
    position_x:          float
    position_y:          float
    depth_m:             Optional[float]
    velocity_x:          float
    velocity_y:          float
    position_uncertainty_m: float
    vehicle_id:          Optional[str]
    last_observation_at: Optional[datetime]


@dataclass
class PredictiveView:
    """Future-path envelope and zone intersection forecast."""
    horizon_s:  float
    zone_hits:  list        # List[ZoneHit]
    uncertain:  bool
    n_samples:  int


@dataclass
class AuthorizationView:
    """Which mission or restriction applies; unresolved associations."""
    verdict:    AuthorizationVerdict
    mission_id: Optional[str]
    findings:   list        # List[PolicyFinding]


@dataclass
class EvidenceQuality:
    """Data-quality summary: staleness, uncertainty, coverage gaps."""
    position_uncertainty_m:  float
    identity_verified:       bool
    last_updated_at:         Optional[datetime]
    stale:                   bool
    notes:                   List[str] = field(default_factory=list)


@dataclass
class HumanHandoffPackage:
    """
    Full incident dossier for officer review.

    ``incident_history`` is the FSM audit trail.
    ``outstanding_questions`` are unanswered evidence gaps.
    """
    incident_id:          str
    track_id:             str
    incident_state:       IncidentState
    handoff_at:           Optional[datetime]
    acknowledged_at:      Optional[datetime]
    incident_history:     list   # List[IncidentTransition]
    outstanding_questions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Course-of-action card  (structure.md table)
# ---------------------------------------------------------------------------

@dataclass
class CourseOfActionCard:
    """
    Shareable one-record summary suitable for operator display.

    Fields match the CoA card specification in structure.md.
    """
    recommendation:      str
    reason:              str
    supporting_evidence: List[str]
    uncertainty:         str
    next_useful_evidence: Optional[str]
    reassessment_trigger: Optional[str]
    human_status:        str    # e.g. "Handoff pending acknowledgment"


# ---------------------------------------------------------------------------
# Decision package
# ---------------------------------------------------------------------------

@dataclass
class DecisionPackage:
    """
    Versioned output of the Level-2 decision engine for one track.

    ``package_id`` and ``generated_at`` support replay and deduplication
    (inference.md §decision record).
    ``verified`` indicates the recommendation passed the final gate.
    """
    package_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    verified:      bool = False
    rejection_reason: Optional[str] = None

    situation:     Optional[SituationView]     = None
    predictive:    Optional[PredictiveView]    = None
    authorization: Optional[AuthorizationView] = None
    evidence:      Optional[EvidenceQuality]   = None
    coa_card:      Optional[CourseOfActionCard] = None
    handoff:       Optional[HumanHandoffPackage] = None

    def to_display_dict(self) -> dict:
        """Shallow dict for console / dashboard rendering."""
        return {
            "package_id":     self.package_id[:8],
            "generated_at":   self.generated_at.isoformat(),
            "verified":       self.verified,
            "track_id":       self.situation.track_id if self.situation else None,
            "recommendation": self.coa_card.recommendation if self.coa_card else None,
            "reason":         self.coa_card.reason if self.coa_card else None,
            "incident_state": self.handoff.incident_state.value if self.handoff else None,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_package(
    track:            TrackState,
    forecast:         TrajectoryForecast,
    policy:           PolicyResult,
    incident:         Incident,
    plan:             ActionPlan,
    verified:         bool,
    rejection_reason: Optional[str] = None,
    generated_at:     Optional[datetime] = None,
) -> DecisionPackage:
    """Assemble a DecisionPackage from individual component outputs."""
    now = generated_at or datetime.now(timezone.utc)

    # Staleness check: > 60 s since last track update
    stale = False
    stale_notes: List[str] = []
    if track.updated_at:
        updated = track.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = (now - updated).total_seconds()
        if age > 60:
            stale = True
            stale_notes.append(f"Position estimate is {age:.0f}s old.")
    if track.vehicle_id is None:
        stale_notes.append("Vehicle identity is unverified.")

    # Outstanding questions for the handoff package
    questions: List[str] = []
    for finding in policy.findings:
        if finding.severity == "alert":
            questions.append(finding.description)
    if plan.next_useful_evidence:
        questions.append(f"Useful next evidence: {plan.next_useful_evidence}")

    # Human status string
    human_status_map = {
        IncidentState.WATCHING:        "Monitoring",
        IncidentState.VERIFYING:       "Verifying",
        IncidentState.HANDOFF_PENDING: "Handoff pending acknowledgment",
        IncidentState.HUMAN_OWNED:     "Officer owns incident",
        IncidentState.RESOLVED:        "Resolved",
        IncidentState.ESCALATED:       "Escalated — no acknowledgment",
    }
    human_status = human_status_map.get(incident.state, incident.state.value)

    px, py, pz = track.position
    vx, vy, _  = track.velocity

    return DecisionPackage(
        generated_at  = now,
        verified      = verified,
        rejection_reason = rejection_reason,
        situation     = SituationView(
            track_id             = track.track_id,
            position_x           = px,
            position_y           = py,
            depth_m              = pz if pz else None,
            velocity_x           = vx,
            velocity_y           = vy,
            position_uncertainty_m = track.position_uncertainty_m,
            vehicle_id           = track.vehicle_id,
            last_observation_at  = track.updated_at,
        ),
        predictive    = PredictiveView(
            horizon_s  = forecast.horizon_s,
            zone_hits  = forecast.zone_hits,
            uncertain  = forecast.uncertain,
            n_samples  = len(forecast.samples),
        ),
        authorization = AuthorizationView(
            verdict    = policy.verdict,
            mission_id = policy.mission_id,
            findings   = policy.findings,
        ),
        evidence      = EvidenceQuality(
            position_uncertainty_m = track.position_uncertainty_m,
            identity_verified      = track.vehicle_id is not None,
            last_updated_at        = track.updated_at,
            stale                  = stale,
            notes                  = stale_notes,
        ),
        coa_card      = CourseOfActionCard(
            recommendation       = plan.action_id.value,
            reason               = plan.reason,
            supporting_evidence  = plan.supporting_evidence,
            uncertainty          = plan.uncertainty_note or "",
            next_useful_evidence = plan.next_useful_evidence,
            reassessment_trigger = plan.reassessment_trigger,
            human_status         = human_status,
        ),
        handoff       = HumanHandoffPackage(
            incident_id           = incident.incident_id,
            track_id              = track.track_id,
            incident_state        = incident.state,
            handoff_at            = incident.handoff_at,
            acknowledged_at       = incident.acknowledged_at,
            incident_history      = list(incident.history),
            outstanding_questions = questions,
        ),
    )
