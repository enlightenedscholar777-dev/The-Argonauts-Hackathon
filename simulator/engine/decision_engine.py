"""
Level 2 — Decision engine facade.

Accepts accepted Observations from the Level-1 journal and returns a
versioned DecisionPackage.  All component interactions are orchestrated here.

Execution order (structure.md §"How the components cooperate"):
    1. KalmanTracker   — update track estimate
    2. TrajectoryPredictor — look-ahead rollouts
    3. PolicyEngine    — authorization and rule checks
    4. IncidentManager — advance FSM; check deadlines
    5. ActionPlanner   — select recommended action (deterministic path)
    6. ActionVerifier  — gate before output
    7. AIBranch        — optional async enrichment (separate call)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from simulator.data_models.observation import Observation
from simulator.data_models.records import Mission, Zone
from simulator.engine.ai_branch.ai_branch import AIBranch, AIProposal
from simulator.engine.incident.incident_fsm import (
    Incident,
    IncidentEvent,
    IncidentManager,
    IncidentState,
)
from simulator.engine.planner.action_planner import ActionID, ActionPlan, ActionPlanner
from simulator.engine.policy.policy_engine import PolicyEngine, PolicyResult
from simulator.engine.predictor.trajectory_predictor import (
    TrajectoryForecast,
    TrajectoryPredictor,
)
from simulator.engine.tracker.kalman_tracker import KalmanTracker, TrackState
from simulator.engine.verifier.action_verifier import ActionVerifier, VerificationResult
from simulator.output.decision_package import DecisionPackage, build_package


class DecisionEngine:
    """
    Facade for the Level-2 hybrid decision engine.

    ``process(obs)`` runs the immediate CPU assessment path synchronously.
    ``enrich_with_ai(track_id)`` runs the optional AI branch (call after
    ``process`` has returned to avoid delaying the initial recommendation).
    """

    def __init__(
        self,
        missions: Optional[List[Mission]] = None,
        zones:    Optional[List[Zone]]    = None,
        response_window_s: float           = 60.0,
        forecast_horizon_s: float          = 120.0,
    ) -> None:
        self.missions: List[Mission] = missions or []
        self.zones:    List[Zone]    = zones    or []

        self._tracker   = KalmanTracker()
        self._predictor = TrajectoryPredictor(horizon_s=forecast_horizon_s)
        self._policy    = PolicyEngine()
        self._incidents = IncidentManager()
        self._planner   = ActionPlanner(response_window_s=response_window_s)
        self._verifier  = ActionVerifier()
        self._ai        = AIBranch()

        # Last results per track for the output builder
        self._last_policy:   Dict[str, PolicyResult]      = {}
        self._last_forecast: Dict[str, TrajectoryForecast] = {}
        self._last_plan:     Dict[str, ActionPlan]         = {}
        self._last_verify:   Dict[str, VerificationResult] = {}

    # ------------------------------------------------------------------
    def process(
        self,
        obs: Observation,
        now: Optional[datetime] = None,
    ) -> Optional[DecisionPackage]:
        """
        Run the immediate CPU assessment path for one accepted observation.

        Returns a ``DecisionPackage`` or None when the observation does not
        produce a track update (e.g., non-tracking measurement types).
        """
        wall = now or datetime.now(timezone.utc)

        # 1. Tracker
        track = self._tracker.update(obs)
        if track is None:
            return None

        # 2. Predictor
        forecast = self._predictor.forecast(track, self.zones)
        self._last_forecast[track.track_id] = forecast

        # 3. Policy
        policy = self._policy.evaluate(track, self.missions, self.zones, wall)
        self._last_policy[track.track_id] = policy

        # 4. Incident FSM
        incident = self._incidents.get_or_create(track.track_id)
        if policy.requires_attention:
            self._incidents.advance(
                track.track_id, IncidentEvent.CONCERN_RAISED, wall,
                note="; ".join(f.code for f in policy.findings),
            )
        else:
            self._incidents.advance(track.track_id, IncidentEvent.EVIDENCE_UPDATED, wall)
        incident = self._incidents.get_or_create(track.track_id)  # re-fetch after advance

        # 5. Planner
        plan = self._planner.plan(track, policy, forecast, incident.state)
        self._last_plan[track.track_id] = plan

        # Advance incident if handoff is recommended
        if plan.action_id == ActionID.HANDOFF_TO_OFFICER:
            self._incidents.advance(
                track.track_id, IncidentEvent.HANDOFF_REQUESTED, wall,
                note=plan.reason,
            )

        # 6. Verifier
        result = self._verifier.verify(plan, track, wall)
        self._last_verify[track.track_id] = result

        # 7. Check deadlines across all incidents
        self._incidents.check_deadlines(wall)

        return build_package(
            track=track,
            forecast=forecast,
            policy=policy,
            incident=incident,
            plan=result.plan or plan,
            verified=result.accepted,
            rejection_reason=result.reason if not result.accepted else None,
            generated_at=wall,
        )

    # ------------------------------------------------------------------
    def enrich_with_ai(
        self,
        track_id: str,
        thinking_mode: bool = False,
    ) -> Optional[AIProposal]:
        """
        Run the optional AI branch for ``track_id``.

        Should be called *after* ``process()`` has returned its initial
        recommendation.  Returns an ``AIProposal`` that the caller should
        pass back through ``verify_ai_proposal()`` before showing.
        """
        track   = self._tracker.tracks.get(track_id)
        policy  = self._last_policy.get(track_id)
        if track is None or policy is None:
            return None

        snapshot = {
            "track_id":       track_id,
            "vehicle_id":     track.vehicle_id,
            "position_uncertainty_m": track.position_uncertainty_m,
            "policy_verdict": policy.verdict.value,
            "findings": [
                {"code": f.code, "description": f.description}
                for f in policy.findings
            ],
        }
        return self._ai.analyse(snapshot, thinking_mode=thinking_mode)

    # ------------------------------------------------------------------
    def verify_ai_proposal(
        self,
        track_id: str,
        proposal: AIProposal,
        now: Optional[datetime] = None,
    ) -> VerificationResult:
        """Validate an AI-generated proposal against the current state."""
        track = self._tracker.tracks.get(track_id)
        if track is None:
            from simulator.engine.verifier.action_verifier import VerificationResult
            return VerificationResult.reject(f"unknown track_id {track_id}")

        if proposal.action_id is None:
            return VerificationResult.reject("AI proposal has no action_id")

        plan = ActionPlan(
            action_id=ActionID(proposal.action_id),
            reason=proposal.explanation or "",
            supporting_evidence=proposal.evidence_ids,
            uncertainty_note=proposal.uncertainty_note,
        )
        return self._verifier.verify(plan, track, now)

    # ------------------------------------------------------------------
    def operator_acknowledge(self, track_id: str, now: Optional[datetime] = None) -> Incident:
        """Record that the officer has acknowledged the handoff for ``track_id``."""
        return self._incidents.advance(
            track_id, IncidentEvent.HUMAN_ACKNOWLEDGED,
            now or datetime.now(timezone.utc),
            note="operator acknowledged via console",
        )

    # ------------------------------------------------------------------
    def operator_resolve(self, track_id: str, now: Optional[datetime] = None) -> Incident:
        """Record that the officer has resolved the incident for ``track_id``."""
        return self._incidents.advance(
            track_id, IncidentEvent.RESOLVED,
            now or datetime.now(timezone.utc),
            note="officer confirmed safe / departed",
        )
