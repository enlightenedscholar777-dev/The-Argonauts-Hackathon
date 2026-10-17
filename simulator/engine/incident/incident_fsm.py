"""
Level 2 — Incident finite-state machine (FSM).

Tracks the lifecycle of each security / safety incident from initial
detection through human acknowledgment.

structure.md: "Incident management — Finite-state machine
→ Watching, verifying, handoff pending, human owned"

States
------
    WATCHING         — track exists; no immediate concern
    VERIFYING        — concerning findings; awaiting more evidence
    HANDOFF_PENDING  — recommendation issued; awaiting human acknowledgment
    HUMAN_OWNED      — officer has accepted responsibility
    RESOLVED         — incident closed (operator confirmed safe / departed)
    ESCALATED        — response deadline exceeded without acknowledgment

Valid transitions are enforced.  Any event that cannot advance the current
state is logged and silently ignored (no partial updates).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# States and events
# ---------------------------------------------------------------------------

class IncidentState(str, Enum):
    WATCHING        = "watching"
    VERIFYING       = "verifying"
    HANDOFF_PENDING = "handoff_pending"
    HUMAN_OWNED     = "human_owned"
    RESOLVED        = "resolved"
    ESCALATED       = "escalated"


class IncidentEvent(str, Enum):
    CONCERN_RAISED      = "concern_raised"       # policy finding or zone hit
    EVIDENCE_UPDATED    = "evidence_updated"      # new observation refines picture
    HANDOFF_REQUESTED   = "handoff_requested"     # action planner recommends human review
    HUMAN_ACKNOWLEDGED  = "human_acknowledged"    # operator accepts the handoff
    RESOLVED            = "resolved"              # officer clears the incident
    RESPONSE_DEADLINE   = "response_deadline"     # handoff unanswered too long


# Allowed transitions:  (current_state, event) → next_state
_TRANSITIONS: Dict[tuple, IncidentState] = {
    (IncidentState.WATCHING,        IncidentEvent.CONCERN_RAISED):     IncidentState.VERIFYING,
    (IncidentState.WATCHING,        IncidentEvent.HANDOFF_REQUESTED):  IncidentState.HANDOFF_PENDING,
    (IncidentState.VERIFYING,       IncidentEvent.EVIDENCE_UPDATED):   IncidentState.VERIFYING,
    (IncidentState.VERIFYING,       IncidentEvent.HANDOFF_REQUESTED):  IncidentState.HANDOFF_PENDING,
    (IncidentState.VERIFYING,       IncidentEvent.RESOLVED):           IncidentState.RESOLVED,
    (IncidentState.HANDOFF_PENDING, IncidentEvent.HUMAN_ACKNOWLEDGED): IncidentState.HUMAN_OWNED,
    (IncidentState.HANDOFF_PENDING, IncidentEvent.RESPONSE_DEADLINE):  IncidentState.ESCALATED,
    (IncidentState.HANDOFF_PENDING, IncidentEvent.EVIDENCE_UPDATED):   IncidentState.HANDOFF_PENDING,
    (IncidentState.HUMAN_OWNED,     IncidentEvent.RESOLVED):           IncidentState.RESOLVED,
    (IncidentState.HUMAN_OWNED,     IncidentEvent.EVIDENCE_UPDATED):   IncidentState.HUMAN_OWNED,
    (IncidentState.ESCALATED,       IncidentEvent.HUMAN_ACKNOWLEDGED): IncidentState.HUMAN_OWNED,
    (IncidentState.ESCALATED,       IncidentEvent.EVIDENCE_UPDATED):   IncidentState.ESCALATED,
}


# ---------------------------------------------------------------------------
# Incident record
# ---------------------------------------------------------------------------

@dataclass
class IncidentTransition:
    from_state: IncidentState
    to_state:   IncidentState
    event:      IncidentEvent
    at:         datetime
    note:       str = ""


@dataclass
class Incident:
    """
    One incident lifecycle for a single track.

    ``history`` provides the full audit trail for the human-handoff package.
    """
    incident_id:      str = field(default_factory=lambda: str(uuid.uuid4()))
    track_id:         str = ""
    state:            IncidentState = IncidentState.WATCHING
    created_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    handoff_at:       Optional[datetime] = None
    acknowledged_at:  Optional[datetime] = None
    history:          List[IncidentTransition] = field(default_factory=list)
    # Deadline for human acknowledgment (seconds after handoff)
    acknowledgment_deadline_s: float = 120.0

    def acknowledgment_overdue(self, now: datetime) -> bool:
        if self.state != IncidentState.HANDOFF_PENDING or self.handoff_at is None:
            return False
        return (now - self.handoff_at).total_seconds() > self.acknowledgment_deadline_s


# ---------------------------------------------------------------------------
# FSM manager
# ---------------------------------------------------------------------------

class IncidentManager:
    """
    Creates and advances Incident records.

    One Incident per track_id.  Returns the current Incident state after
    processing an event.
    """

    def __init__(self) -> None:
        self._incidents: Dict[str, Incident] = {}   # track_id → Incident

    # ------------------------------------------------------------------
    def get_or_create(self, track_id: str) -> Incident:
        if track_id not in self._incidents:
            self._incidents[track_id] = Incident(track_id=track_id)
        return self._incidents[track_id]

    # ------------------------------------------------------------------
    def advance(
        self,
        track_id: str,
        event: IncidentEvent,
        now: Optional[datetime] = None,
        note: str = "",
    ) -> Incident:
        """
        Apply ``event`` to the incident for ``track_id``.

        Invalid transitions are silently ignored (the FSM stays in its
        current state) to prevent duplicate or stale events from corrupting
        the incident record.
        """
        incident = self.get_or_create(track_id)
        wall = now or datetime.now(timezone.utc)
        key  = (incident.state, event)

        next_state = _TRANSITIONS.get(key)
        if next_state is None:
            return incident   # no-op for invalid transitions

        transition = IncidentTransition(
            from_state=incident.state,
            to_state=next_state,
            event=event,
            at=wall,
            note=note,
        )
        incident.history.append(transition)
        incident.state          = next_state
        incident.last_updated_at = wall

        if next_state == IncidentState.HANDOFF_PENDING:
            incident.handoff_at = wall
        if next_state == IncidentState.HUMAN_OWNED:
            incident.acknowledged_at = wall

        return incident

    # ------------------------------------------------------------------
    def check_deadlines(self, now: Optional[datetime] = None) -> List[Incident]:
        """
        Advance any HANDOFF_PENDING incidents whose acknowledgment deadline
        has passed.  Returns the list of escalated incidents.
        """
        wall = now or datetime.now(timezone.utc)
        escalated = []
        for incident in self._incidents.values():
            if incident.acknowledgment_overdue(wall):
                self.advance(incident.track_id, IncidentEvent.RESPONSE_DEADLINE, wall,
                             "acknowledgment deadline exceeded")
                escalated.append(incident)
        return escalated

    # ------------------------------------------------------------------
    @property
    def all_incidents(self) -> List[Incident]:
        return list(self._incidents.values())
