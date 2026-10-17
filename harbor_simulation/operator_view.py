"""Operator-facing language over engine results; no independent risk decisions."""

ACTION_LABELS = {
    "MONITOR": "Continue monitoring",
    "VERIFY_PERMISSION": "Verify operating permission",
    "REQUEST_FRESH_OBSERVATION": "Request a fresh position report",
    "CONTACT_OPERATOR": "Contact the vehicle operator",
    "HUMAN_REVIEW": "Review this contact now",
}
ACTION_DETAILS = {
    "MONITOR": "Keep this contact under observation and review any change in its assessment.",
    "VERIFY_PERMISSION": "Check the contact's identity and operating permission with an authorized operator.",
    "REQUEST_FRESH_OBSERVATION": "Obtain a new position observation before relying on the displayed location or forecast.",
    "CONTACT_OPERATOR": "Ask the vehicle operator to confirm its route, status and intended activity.",
    "HUMAN_REVIEW": "Review the position, zone evidence and permissions, then decide the appropriate response under port procedures.",
}
REASONS = {
    "TRACK_DATA_LOST": "Position updates have been lost; the displayed position is no longer current.",
    "TRACK_DATA_STALE": "The last position report is getting old and needs refreshing.",
    "SENSOR_CONFLICT": "Recent position reports disagree with the established track.",
    "CLOCK_UNCERTAIN": "Observation timing is uncertain.",
    "FILTER_UNAVAILABLE": "A reliable position estimate is unavailable.",
    "HAZARD_ZONE_OCCUPIED": "The estimated position is inside a demo hazard zone.",
    "RESTRICTED_ZONE_PERMISSION_UNCONFIRMED": "The contact is estimated inside a restricted demo zone without confirmed permission.",
    "RESTRICTED_ZONE_PERMISSION_DENIED": "The contact is estimated inside a restricted demo zone without permission.",
    "PROJECTED_ZONE_ENTRY": "The current motion forecast indicates an imminent demo zone entry.",
    "PROJECTED_ZONE_APPROACH": "The current motion forecast approaches a demo policy zone.",
    "POSITION_UNCERTAINTY_NEAR_ZONE": "Position uncertainty extends close to a demo zone boundary.",
    "ROUTE_DEVIATION": "The contact has moved away from its assigned route.",
    "EXPECTED_COMMUNICATION_MISSING": "An expected vehicle status message has not arrived.",
    "IDENTITY_UNCONFIRMED": "The contact's identity and operating permission have not been confirmed.",
    "MISSION_PERMISSION_DENIED": "The assigned mission does not grant the required permission.",
    "WITHIN_DEMO_MISSION_CONSTRAINTS": "The contact is within its assigned demo mission constraints.",
}
QUALITY_LABELS = {
    "FRESH": "Current position",
    "STALE": "Position needs updating",
    "LOST": "Position updates lost",
    "CONFLICT": "Conflicting position reports",
    "INSUFFICIENT_HISTORY": "Building position history",
}
RISK_LABELS = {
    "HIGH": "High concern",
    "ELEVATED": "Elevated concern",
    "LOW": "Low concern",
    "UNKNOWN": "Uncertain",
}


def contact_name(track_id):
    for prefix, label in (
        ("research_auv_", "Research vehicle"),
        ("unknown_", "Unidentified contact"),
        ("contact_", "Contact"),
    ):
        if track_id.startswith(prefix):
            return f"{label} {track_id[len(prefix) :]}"
    return track_id.replace("_", " ").capitalize()


def needs_attention(track):
    return track["recommendation"]["primary_action"] != "MONITOR" or bool(
        track.get("incident") and track["incident"].get("handoff_required")
    )


def priority(track):
    """Order the queue using existing handoff, risk and action fields only."""
    return (
        not bool(track.get("incident") and track["incident"].get("handoff_required")),
        {"HIGH": 0, "UNKNOWN": 1, "ELEVATED": 2, "LOW": 3}.get(track["risk"]["current_band"], 4),
        {
            "HUMAN_REVIEW": 0,
            "REQUEST_FRESH_OBSERVATION": 1,
            "CONTACT_OPERATOR": 2,
            "VERIFY_PERMISSION": 3,
            "MONITOR": 4,
        }.get(track["recommendation"]["primary_action"], 5),
        track["track_id"],
    )


def explanation(track):
    reasons = track["risk"]["reason_codes"]
    return (
        " ".join(REASONS.get(reason, reason.replace("_", " ").capitalize() + ".") for reason in reasons)
        or track["recommendation"]["deterministic_explanation"]
    )


def review_state(track):
    incident = track.get("incident")
    if incident and incident.get("handoff_required"):
        return "Review requested"
    if incident and incident["state"] == "HUMAN_OWNED":
        return "Review acknowledged"
    if incident and incident["state"] == "CLOSED":
        return "Incident closed"
    return "Awaiting verification" if needs_attention(track) else "Monitoring"
