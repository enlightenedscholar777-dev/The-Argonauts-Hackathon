"""
Level 2 — Policy rules and authorization assessment.

Implements typed policy rules that check:
  - Whether a track is within a Zone it is authorized for.
  - Whether an active Mission covers the current position and time.
  - Whether a cooperative vehicle's contact schedule is current.

Returns a ``PolicyResult`` with an authorization verdict and a list of
specific findings for the action planner.

structure.md: "Authorization assessment — Typed policy rules
→ Authorized, unknown, or outside approved scope"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from simulator.data_models.records import Mission, Zone, ZoneRestriction
from simulator.engine.tracker.kalman_tracker import TrackState


# ---------------------------------------------------------------------------
# Enumerations and result types
# ---------------------------------------------------------------------------

class AuthorizationVerdict(str, Enum):
    AUTHORIZED        = "authorized"
    UNKNOWN           = "unknown"           # identity not established
    OUTSIDE_SCOPE     = "outside_scope"     # in restricted area without permit
    MISSION_EXPIRED   = "mission_expired"
    CONTACT_OVERDUE   = "contact_overdue"
    NO_MISSION_FOUND  = "no_mission_found"


@dataclass
class PolicyFinding:
    """A specific policy violation or concern."""
    code:        str
    description: str
    severity:    str  # "info" | "warning" | "alert"


@dataclass
class PolicyResult:
    """Output of the policy engine for one track at one moment in time."""
    track_id:   str
    verdict:    AuthorizationVerdict
    findings:   List[PolicyFinding] = field(default_factory=list)
    mission_id: Optional[str] = None   # matching mission, if found

    @property
    def requires_attention(self) -> bool:
        return self.verdict not in (AuthorizationVerdict.AUTHORIZED,)


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    Evaluates typed rules against a track state, missions, and zones.

    Rules are evaluated independently and accumulated into findings.
    A plausible trajectory does NOT prove vehicle identity — the engine
    treats identity association as a separate, explicit step.
    """

    # ------------------------------------------------------------------
    def evaluate(
        self,
        track: TrackState,
        missions: List[Mission],
        zones: List[Zone],
        now: datetime,
    ) -> PolicyResult:
        findings: List[PolicyFinding] = []
        verdict  = AuthorizationVerdict.UNKNOWN
        matched_mission: Optional[Mission] = None

        px, py, pz = track.position

        # --- Rule 1: identity check ---
        if track.vehicle_id is None:
            findings.append(PolicyFinding(
                code="UNKNOWN_IDENTITY",
                description="Track has no verified cooperative identity.",
                severity="warning",
            ))

        # --- Rule 2: find a matching mission ---
        for mission in missions:
            if not mission.is_active_at(now):
                continue
            if track.vehicle_id and mission.vehicle_id != track.vehicle_id:
                continue
            # Check spatial coverage
            if mission.permitted_area is not None:
                area = mission.permitted_area
                if not (area.x_min <= px <= area.x_max and area.y_min <= py <= area.y_max):
                    findings.append(PolicyFinding(
                        code="OUTSIDE_PERMITTED_AREA",
                        description=f"Track at ({px:.0f},{py:.0f}) is outside mission {mission.mission_id[:8]} area.",
                        severity="alert",
                    ))
                    verdict = AuthorizationVerdict.OUTSIDE_SCOPE
                    matched_mission = mission
                    continue
            matched_mission = mission

        if matched_mission is None and track.vehicle_id is not None:
            findings.append(PolicyFinding(
                code="NO_ACTIVE_MISSION",
                description=f"No active mission found for vehicle {track.vehicle_id}.",
                severity="alert",
            ))
            verdict = AuthorizationVerdict.NO_MISSION_FOUND
        elif matched_mission is not None and verdict == AuthorizationVerdict.UNKNOWN:
            verdict = AuthorizationVerdict.AUTHORIZED

        # --- Rule 3: contact schedule ---
        if matched_mission and matched_mission.contact_overdue(now):
            findings.append(PolicyFinding(
                code="CONTACT_OVERDUE",
                description=f"Vehicle {matched_mission.vehicle_id} has missed its expected check-in.",
                severity="alert",
            ))
            verdict = AuthorizationVerdict.CONTACT_OVERDUE

        # --- Rule 4: zone restrictions ---
        for zone in zones:
            if not zone.is_active_at(now):
                continue
            if not zone.contains_point(px, py):
                continue
            # Depth check
            if pz is not None and zone.depth_min is not None and zone.depth_max is not None:
                if not (zone.depth_min <= -pz <= zone.depth_max):   # depth positive down
                    continue
            if zone.restriction in (ZoneRestriction.RESTRICTED, ZoneRestriction.PROHIBITED):
                authorized_in_zone = (
                    matched_mission is not None
                    and verdict == AuthorizationVerdict.AUTHORIZED
                )
                if not authorized_in_zone:
                    findings.append(PolicyFinding(
                        code="UNAUTHORIZED_ZONE_ENTRY",
                        description=(
                            f"Track is inside {zone.restriction.value} zone "
                            f"'{zone.name}' without verified authorization."
                        ),
                        severity="alert",
                    ))
                    verdict = AuthorizationVerdict.OUTSIDE_SCOPE

        return PolicyResult(
            track_id=track.track_id,
            verdict=verdict,
            findings=findings,
            mission_id=matched_mission.mission_id if matched_mission else None,
        )
