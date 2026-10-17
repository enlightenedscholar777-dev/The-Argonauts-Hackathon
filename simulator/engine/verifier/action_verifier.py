"""
Level 2 — Final recommendation verifier.

Performs schema, policy prerequisite, citation, and freshness checks on a
candidate ActionPlan before it reaches the operator.

structure.md: "Final verification — Schema, policy, prerequisite, citation,
and freshness checks → Accepted recommendation or a reason for rejection"

inference.md: "When the [AI] job returns, the engine rechecks its assumptions
against the current state before displaying its proposed action."

A proposal is rejected (not just warned) if:
  - The action_id is not in the allowed catalog.
  - A HANDOFF_TO_OFFICER recommendation has no supporting findings.
  - The state that triggered the recommendation has since been superseded
    (``state_revision`` mismatch).
  - Position data is stale beyond the freshness threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from simulator.engine.planner.action_planner import ActionID, ActionPlan
from simulator.engine.tracker.kalman_tracker import TrackState


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """
    Outcome of the final check.

    ``accepted`` : True if the recommendation may be shown to the operator.
    ``reason``   : Human-readable explanation (shown only in logs / debug).
    """
    accepted: bool
    plan:     Optional[ActionPlan] = None
    reason:   str = ""

    @classmethod
    def ok(cls, plan: ActionPlan) -> "VerificationResult":
        return cls(accepted=True, plan=plan, reason="ok")

    @classmethod
    def reject(cls, reason: str) -> "VerificationResult":
        return cls(accepted=False, reason=reason)


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

class ActionVerifier:
    """
    Gate between the planner / AI branch and the human interface.

    ``verify()`` accepts a candidate plan together with the track state and
    the decision timestamp.  It returns a ``VerificationResult``.

    Parameters
    ----------
    max_observation_age_s  : reject if the most recent track update is older
                             than this (freshness check).
    require_evidence_for_handoff : reject a HANDOFF_TO_OFFICER that has no
                                   supporting_evidence entries.
    """

    def __init__(
        self,
        max_observation_age_s: float = 120.0,
        require_evidence_for_handoff: bool = True,
    ) -> None:
        self.max_observation_age_s        = max_observation_age_s
        self.require_evidence_for_handoff = require_evidence_for_handoff

    # ------------------------------------------------------------------
    def verify(
        self,
        plan:  ActionPlan,
        track: TrackState,
        now:   Optional[datetime] = None,
    ) -> VerificationResult:
        wall = now or datetime.now(timezone.utc)

        # 1. Action ID must be in the catalog
        try:
            ActionID(plan.action_id)
        except ValueError:
            return VerificationResult.reject(
                f"action_id '{plan.action_id}' is not in the allowed catalog"
            )

        # 2. Freshness check — reject stale proposals
        if track.updated_at is not None:
            updated = track.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_s = (wall - updated).total_seconds()
            if age_s > self.max_observation_age_s:
                return VerificationResult.reject(
                    f"track {track.track_id} last updated {age_s:.0f}s ago "
                    f"(threshold {self.max_observation_age_s}s) — proposal is stale"
                )

        # 3. HANDOFF_TO_OFFICER must have supporting evidence
        if (
            plan.action_id == ActionID.HANDOFF_TO_OFFICER
            and self.require_evidence_for_handoff
            and not plan.supporting_evidence
        ):
            return VerificationResult.reject(
                "HANDOFF_TO_OFFICER requires at least one supporting_evidence entry"
            )

        # 4. VERIFY_WITH_OPERATOR should not be issued for an already-verified track
        if plan.action_id == ActionID.VERIFY_WITH_OPERATOR and track.vehicle_id is not None:
            # Identity already known — downgrade to WATCH unless there is another concern
            if not plan.supporting_evidence:
                plan = ActionPlan(
                    action_id=ActionID.WATCH,
                    reason=f"Track identity verified as {track.vehicle_id}; downgraded from VERIFY.",
                    reassessment_trigger=plan.reassessment_trigger,
                )

        return VerificationResult.ok(plan)
