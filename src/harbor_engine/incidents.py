import copy
import uuid

from .clock import stamp


def reconcile(session, track_id):
    track = session["tracks"][track_id]
    assessment = track["assessment"]
    action = assessment["recommendation"]["primary_action"]
    incident = track.get("incident")
    if incident and incident["state"] == "CLOSED":
        incident = None
    if incident is None and action != "MONITOR":
        incident = {
            "schema_version": "1.0",
            "incident_id": "inc_" + uuid.uuid4().hex,
            "track_id": track_id,
            "state": "VERIFYING" if action == "VERIFY_PERMISSION" else "WATCHING",
            "opened_at": stamp(session["now"]),
            "highest_historical_risk": "UNKNOWN",
            "highest_risk_evidence": [],
            "acknowledgment": None,
            "handoff_required": False,
        }
    if incident:
        if action == "HUMAN_REVIEW" and incident["state"] != "HUMAN_OWNED":
            incident["handoff_required"] = True
            incident["state"] = "HANDOFF_PENDING"
        ranks = {"UNKNOWN": -1, "LOW": 0, "ELEVATED": 1, "HIGH": 2}
        risk = assessment["risk"]["current_band"]
        if ranks[risk] >= ranks[incident["highest_historical_risk"]]:
            incident["highest_historical_risk"] = risk
            incident["highest_risk_evidence"] = copy.deepcopy(assessment["evidence"])
        incident["current_risk"] = risk
        incident["updated_at"] = stamp(session["now"])
        assessment["risk"]["historical_incident_maximum"] = incident["highest_historical_risk"]
        if incident["handoff_required"]:
            assessment["recommendation"]["outstanding_human_handoff"] = True
        track["incident"] = incident
        assessment["incident"] = copy.deepcopy(incident)
