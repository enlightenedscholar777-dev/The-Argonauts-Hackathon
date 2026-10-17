"""
Level 2 — Action planner.

Selects from a fixed, enumerated action catalog based on risk findings,
evidence gaps, and a one-step value-of-information estimate.

structure.md: "Action planning — Constrained action enumeration +
one-step value-of-information estimate → Recommended action and useful
next information request"

The action catalog is the single source of truth for what the system can
recommend.  The AI branch and planner may only propose action IDs from this
catalog; the verifier rejects anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from simulator.engine.incident.incident_fsm import IncidentState
from simulator.engine.policy.policy_engine import AuthorizationVerdict, PolicyResult
from simulator.engine.predictor.trajectory_predictor import TrajectoryForecast
from simulator.engine.tracker.kalman_tracker import TrackState


# ---------------------------------------------------------------------------
# Action catalog
# ---------------------------------------------------------------------------

class ActionID(str, Enum):
    WATCH                = "watch"               # continue monitoring, no escalation
    CHECK_MISSION        = "check_mission"       # look up mission registry
    REQUEST_FRESH_OBS    = "request_fresh_obs"   # ask for new sensor data
    VERIFY_WITH_OPERATOR = "verify_with_operator" # contact controlling team
    HANDOFF_TO_OFFICER   = "handoff_to_officer"  # trigger human review
    AWAIT_ACKNOWLEDGMENT = "await_acknowledgment" # handoff sent; waiting
    NO_ACTION_REQUIRED   = "no_action_required"  # incident resolved / authorized


# Urgency weights used in the one-step VoI estimate
_URGENCY: dict[ActionID, int] = {
    ActionID.HANDOFF_TO_OFFICER:   5,
    ActionID.VERIFY_WITH_OPERATOR: 4,
    ActionID.REQUEST_FRESH_OBS:    3,
    ActionID.CHECK_MISSION:        2,
    ActionID.WATCH:                1,
    ActionID.NO_ACTION_REQUIRED:   0,
    ActionID.AWAIT_ACKNOWLEDGMENT: 0,
}


# ---------------------------------------------------------------------------
# Planner output
# ---------------------------------------------------------------------------

@dataclass
class ActionPlan:
    """Recommended action with supporting rationale."""
    action_id:            ActionID
    reason:               str
    supporting_evidence:  List[str]       = field(default_factory=list)
    uncertainty_note:     Optional[str]   = None
    next_useful_evidence: Optional[str]   = None   # value-of-information hint
    reassessment_trigger: Optional[str]   = None


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class ActionPlanner:
    """
    Deterministic action planner.

    Produces an ActionPlan from the current assessment state.  The plan is
    always grounded in explicit findings — there is no opaque score.

    Value-of-information estimate
    -----------------------------
    When evidence gaps are present (unknown identity, stale position, missing
    mission), the planner checks whether gathering that evidence could change
    the decision within the available response window.  If collecting it can
    avoid a more expensive action (handoff), it recommends the cheaper
    information-gathering step first.

    ``response_window_s`` represents the remaining time before a handoff
    becomes mandatory.  When <= 0, the planner skips VoI and immediately
    recommends the highest-urgency action.
    """

    def __init__(self, response_window_s: float = 60.0) -> None:
        self.response_window_s = response_window_s

    # ------------------------------------------------------------------
    def plan(
        self,
        track:    TrackState,
        policy:   PolicyResult,
        forecast: Optional[TrajectoryForecast],
        incident_state: IncidentState,
        response_window_s: Optional[float] = None,
    ) -> ActionPlan:
        window = response_window_s if response_window_s is not None else self.response_window_s

        # Incident already in human hands
        if incident_state in (IncidentState.HUMAN_OWNED, IncidentState.ESCALATED):
            return ActionPlan(
                action_id=ActionID.AWAIT_ACKNOWLEDGMENT,
                reason="Incident is with the officer.",
            )
        if incident_state == IncidentState.RESOLVED:
            return ActionPlan(
                action_id=ActionID.NO_ACTION_REQUIRED,
                reason="Incident resolved.",
            )

        candidates: List[ActionID] = []
        reasons:    List[str]      = []
        evidence:   List[str]      = []
        next_info:  Optional[str]  = None

        # --- Evaluate policy findings ---
        for finding in policy.findings:
            if finding.code in ("UNKNOWN_IDENTITY",):
                candidates.append(ActionID.VERIFY_WITH_OPERATOR)
                reasons.append(finding.description)
            elif finding.code in ("OUTSIDE_PERMITTED_AREA", "UNAUTHORIZED_ZONE_ENTRY"):
                candidates.append(ActionID.HANDOFF_TO_OFFICER)
                reasons.append(finding.description)
                evidence.append(finding.code)
            elif finding.code in ("CONTACT_OVERDUE", "NO_ACTIVE_MISSION"):
                candidates.append(ActionID.CHECK_MISSION)
                reasons.append(finding.description)

        # --- Evaluate zone hits ---
        if forecast:
            for hit in forecast.zone_hits:
                if hit.fraction >= 0.5:
                    candidates.append(ActionID.HANDOFF_TO_OFFICER)
                    reasons.append(
                        f"Trajectory enters {hit.zone_name} "
                        f"({hit.fraction*100:.0f}% of paths, "
                        f"earliest ~{hit.earliest_s:.0f}s)."
                    )
                elif hit.fraction >= 0.2:
                    candidates.append(ActionID.VERIFY_WITH_OPERATOR)
                    reasons.append(f"Some trajectories approach {hit.zone_name}.")

        # --- Stale / uncertain position ---
        if track.position_uncertainty_m > 30.0:
            candidates.append(ActionID.REQUEST_FRESH_OBS)
            reasons.append(
                f"Position uncertainty is {track.position_uncertainty_m:.0f} m."
            )
            next_info = "Fresh position observation from sonar or telemetry."

        if not candidates:
            return ActionPlan(
                action_id=ActionID.WATCH,
                reason="No current concerns. Continuing observation.",
                next_useful_evidence="Any new position observation.",
                reassessment_trigger="New observation, zone entry, or mission change.",
            )

        # --- Select highest-urgency candidate ---
        selected = max(candidates, key=lambda a: _URGENCY.get(a, 0))

        # --- Value-of-information: can we avoid a handoff? ---
        if selected == ActionID.HANDOFF_TO_OFFICER and window > 10.0:
            info_actions = {ActionID.VERIFY_WITH_OPERATOR, ActionID.REQUEST_FRESH_OBS}
            if any(c in info_actions for c in candidates):
                # There is an information-gathering option worth trying first
                selected  = max(
                    (c for c in candidates if c in info_actions),
                    key=lambda a: _URGENCY.get(a, 0),
                )
                reasons.append(
                    f"Gathering evidence may resolve uncertainty within "
                    f"{window:.0f}s response window."
                )

        return ActionPlan(
            action_id=selected,
            reason=" | ".join(reasons),
            supporting_evidence=evidence,
            uncertainty_note=(
                f"Position uncertainty: {track.position_uncertainty_m:.0f} m; "
                f"identity verified: {track.vehicle_id is not None}"
            ),
            next_useful_evidence=next_info,
            reassessment_trigger="New observation, verified mission match, or response deadline.",
        )
