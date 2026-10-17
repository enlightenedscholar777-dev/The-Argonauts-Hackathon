"""Validated demo configuration and transparent, ordered advisory rules."""

import hashlib
import json
import uuid
from typing import Literal

import numpy as np
import yaml
from pydantic import Field, model_validator
from shapely.geometry import Point, Polygon

from .clock import stamp
from .forecast import forecast
from .geometry import route_distance, valid_polygon
from .schemas import ID, Assessment, Strict


class Thresholds(Strict):
    acceleration_sigma: float = Field(0.25, gt=0, le=10)
    initial_velocity_sigma: float = Field(10, gt=0, le=100)
    innovation_gate: float = Field(16, gt=0)
    sigma_min: float = Field(0.2, gt=0)
    sigma_max: float = Field(20, gt=0)
    ingestion_age: float = Field(15, gt=0)
    max_forecast_age: float = Field(15, gt=0, le=30)
    urgent_entry: float = Field(15, gt=0, le=30)
    route_enter_m: float = Field(20, gt=0)
    route_clear_m: float = Field(15, gt=0)
    route_observations: int = Field(3, ge=1, le=20)
    route_span: float = Field(2, ge=0)
    conflict_count: int = Field(3, ge=1)

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.sigma_max < self.sigma_min or self.route_clear_m >= self.route_enter_m:
            raise ValueError("Noise bounds and route hysteresis thresholds must be ordered")
        return self


class Zone(Strict):
    kind: Literal["restricted", "hazard"]
    vertices: list[tuple[float, float]] = Field(min_length=3, max_length=64)

    @model_validator(mode="after")
    def geometry(self):
        if not valid_polygon(self.vertices):
            raise ValueError("Invalid zone polygon")
        return self


class Source(Strict):
    kind: Literal["position", "telemetry", "operator"]
    role: Literal["sensor", "operator"]
    interval_seconds: float = Field(1, gt=0, le=300)
    fresh_intervals: float = Field(3, gt=0)
    lost_intervals: float = Field(10, gt=0)

    @model_validator(mode="after")
    def validity(self):
        if self.lost_intervals <= self.fresh_intervals:
            raise ValueError("Lost threshold must exceed fresh threshold")
        if (self.kind == "operator") != (self.role == "operator"):
            raise ValueError("Operator sources require the operator role")
        return self


class Mission(Strict):
    vehicle_id: ID
    operator_label: str = Field(min_length=1, max_length=80)
    route_id: ID
    start_offset: float
    end_offset: float
    registry_start_offset: float = -60
    registry_end_offset: float = 7200
    permitted_zones: list[ID]
    telemetry_source: ID | None = None
    heartbeat_interval: float = Field(5, gt=0)
    heartbeat_timeout_intervals: float = Field(3, gt=0)


class Policy(Strict):
    version: ID
    registry_version: ID
    procedure_version: ID
    description: str
    bounds: tuple[float, float, float, float]
    zones: dict[ID, Zone]
    routes: dict[ID, list[tuple[float, float]]]
    sources: dict[ID, Source] = Field(max_length=20)
    missions: dict[ID, Mission]
    thresholds: Thresholds
    evidence_response_seconds: dict[ID, float]
    action_catalog: list[ID]
    rule_procedures: dict[ID, ID]

    @model_validator(mode="after")
    def references(self):
        if set(self.action_catalog) != {
            "MONITOR",
            "VERIFY_PERMISSION",
            "REQUEST_FRESH_OBSERVATION",
            "CONTACT_OPERATOR",
            "HUMAN_REVIEW",
        }:
            raise ValueError("Action catalog must contain the five advisory demo actions")
        x0, y0, x1, y1 = self.bounds
        if x1 <= x0 or y1 <= y0:
            raise ValueError("Invalid bounds")
        for vertices in [z.vertices for z in self.zones.values()] + list(self.routes.values()):
            if len(vertices) < 2 or any(not (x0 <= x <= x1 and y0 <= y <= y1) for x, y in vertices):
                raise ValueError("Geometry outside simulation bounds")
        for m in self.missions.values():
            if m.route_id not in self.routes or any(z not in self.zones for z in m.permitted_zones):
                raise ValueError("Unknown mission route/zone")
            if m.end_offset <= m.start_offset or m.registry_end_offset <= m.registry_start_offset:
                raise ValueError("Invalid mission time window")
            if m.telemetry_source and (
                m.telemetry_source not in self.sources or self.sources[m.telemetry_source].kind != "telemetry"
            ):
                raise ValueError("Invalid telemetry source")
        return self


def load_policy(path):
    with open(path, encoding="utf-8") as file:
        return Policy.model_validate(yaml.safe_load(file))


def semantic_digest(assessment, note_revision, generation):
    data = {
        "generation": generation,
        "authorization": assessment["authorization"],
        "risk": assessment["risk"]["current_band"],
        "reasons": assessment["risk"]["reason_codes"],
        "action": assessment["recommendation"]["primary_action"],
        "eligible": assessment["recommendation"]["eligible_next_evidence"],
        "zones": assessment["forecast"]["relevant_zones"],
        "policy": assessment["policy_version"],
        "registry": assessment["registry_version"],
        "note_revision": note_revision,
        "evidence_ids": [e["evidence_id"] for e in assessment["evidence"]],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def assess(session, track_id, policy, settings, accepted=False):
    track, now = session["tracks"][track_id], session["now"]
    th = policy.thresholds
    age = max(0, now - track["last_time"])
    source = policy.sources[track["source_id"]]
    source_time = session["sources"].get(track["source_id"], {}).get("time")
    source_health = (
        "UNKNOWN"
        if source_time is None
        else (
            "ONLINE" if now - source_time <= source.interval_seconds * source.fresh_intervals else "OVERDUE"
        )
    )
    quality = "FRESH"
    if age > source.interval_seconds * source.lost_intervals:
        quality = "LOST"
    elif age > source.interval_seconds * source.fresh_intervals:
        quality = "STALE"
    elif track["consecutive_outliers"] >= th.conflict_count:
        quality = "CONFLICT"
    elif not track["velocity_established"]:
        quality = "INSUFFICIENT_HISTORY"
    if track.get("filter_failed") or session.get("clock_uncertain"):
        quality = "CONFLICT"
    polygons = {key: Polygon(zone.vertices) for key, zone in policy.zones.items()}
    mean, covariance, predicted = forecast(track, now, session["seed"], track_id, polygons, settings, th)
    point = Point(mean[:2])
    binding = track.get("binding")
    mission_id = binding.get("mission_id") if binding and binding["operation"] == "confirm" else None
    mission = policy.missions.get(mission_id)
    elapsed = now - session["start"]
    registry_valid = mission and mission.registry_start_offset <= elapsed <= mission.registry_end_offset
    mission_valid = registry_valid and mission.start_offset <= elapsed <= mission.end_offset
    authorization = "UNKNOWN"
    if mission and registry_valid:
        authorization = "AUTHORIZED" if mission_valid else "NOT_AUTHORIZED"
    elif binding and binding["operation"] == "revoke":
        authorization = "NOT_AUTHORIZED"
    permissions = {
        z: (
            "PERMITTED"
            if mission_valid and z in mission.permitted_zones
            else "DENIED"
            if mission and registry_valid
            else "UNCONFIRMED"
        )
        for z, zone in policy.zones.items()
        if zone.kind == "restricted"
    }
    relevant = [
        z for z, zone in policy.zones.items() if zone.kind == "hazard" or permissions[z] != "PERMITTED"
    ]
    predicted["relevant_zones"] = relevant
    predicted["current_zones"] = [z for z, poly in polygons.items() if poly.covers(point)]
    predicted["nearest_zone_distance_m"] = min((point.distance(p) for p in polygons.values()), default=None)
    route_error = route_distance(mean[:2], policy.routes[mission.route_id]) if mission else None
    predicted["route_cross_track_m"] = route_error
    deviation = track.setdefault("deviation", {"active": False, "count": 0, "clear_count": 0, "since": now})
    if accepted and route_error is not None:
        if route_error > th.route_enter_m:
            if deviation["count"] == 0:
                deviation["since"] = track["last_time"]
            deviation["count"] += 1
            deviation["clear_count"] = 0
            if (
                deviation["count"] >= th.route_observations
                and track["last_time"] - deviation["since"] >= th.route_span
            ):
                deviation["active"] = True
        elif route_error < th.route_clear_m:
            deviation["count"] = 0
            deviation["clear_count"] += 1
            if deviation["clear_count"] >= th.route_observations:
                deviation["active"] = False
    contact = bool(mission and mission_valid and mission.operator_label)
    communication = "NOT_APPLICABLE"
    heartbeat_age = None
    if mission and mission.telemetry_source:
        heartbeat_age = now - track.get("heartbeat_time", binding["time"])
        communication = (
            "OVERDUE"
            if heartbeat_age > mission.heartbeat_interval * mission.heartbeat_timeout_intervals
            else "EXPECTED"
        )
    reasons, matches = [], []

    def rule(reason, risk, action):
        reasons.append(reason)
        matches.append((risk, action))

    if quality in ("LOST", "CONFLICT", "STALE"):
        reason = (
            "TRACK_DATA_LOST"
            if quality == "LOST"
            else "TRACK_DATA_STALE"
            if quality == "STALE"
            else "SENSOR_CONFLICT"
        )
        if session.get("clock_uncertain"):
            reason = "CLOCK_UNCERTAIN"
        if track.get("filter_failed"):
            reason = "FILTER_UNAVAILABLE"
        rule(reason, "ELEVATED" if quality == "STALE" else "UNKNOWN", "REQUEST_FRESH_OBSERVATION")
    else:
        for z in relevant:
            if z in predicted["current_zones"]:
                reason = (
                    "HAZARD_ZONE_OCCUPIED"
                    if policy.zones[z].kind == "hazard"
                    else "RESTRICTED_ZONE_PERMISSION_" + permissions[z]
                )
                rule(reason, "HIGH", "HUMAN_REVIEW")
            entry = predicted["zone_entries"].get(z)
            if entry is not None and entry > 0:
                if entry <= th.urgent_entry:
                    rule("PROJECTED_ZONE_ENTRY", "HIGH", "HUMAN_REVIEW")
                else:
                    rule(
                        "PROJECTED_ZONE_APPROACH",
                        "ELEVATED",
                        "VERIFY_PERMISSION"
                        if authorization == "UNKNOWN"
                        else "CONTACT_OPERATOR"
                        if contact
                        else "HUMAN_REVIEW",
                    )
            if (
                not polygons[z].covers(point)
                and point.distance(polygons[z]) <= predicted["current_uncertainty_radius_m"]
            ):
                rule("POSITION_UNCERTAINTY_NEAR_ZONE", "ELEVATED", "REQUEST_FRESH_OBSERVATION")
        if mission and deviation["active"]:
            rule("ROUTE_DEVIATION", "ELEVATED", "CONTACT_OPERATOR" if contact else "HUMAN_REVIEW")
        if communication == "OVERDUE":
            rule(
                "EXPECTED_COMMUNICATION_MISSING",
                "ELEVATED",
                "CONTACT_OPERATOR" if contact else "REQUEST_FRESH_OBSERVATION",
            )
        if authorization == "UNKNOWN":
            rule("IDENTITY_UNCONFIRMED", "LOW", "VERIFY_PERMISSION")
        elif authorization == "NOT_AUTHORIZED":
            rule("MISSION_PERMISSION_DENIED", "ELEVATED", "VERIFY_PERMISSION")
        if not matches:
            rule("WITHIN_DEMO_MISSION_CONSTRAINTS", "LOW", "MONITOR")
    risk_rank = {"LOW": 0, "ELEVATED": 1, "HIGH": 2, "UNKNOWN": 3}
    action_rank = {
        "MONITOR": 0,
        "VERIFY_PERMISSION": 1,
        "REQUEST_FRESH_OBSERVATION": 2,
        "CONTACT_OPERATOR": 3,
        "HUMAN_REVIEW": 4,
    }
    risk = max((r for r, _ in matches), key=risk_rank.get)
    action = max((a for _, a in matches), key=action_rank.get)
    reasons = sorted(set(reasons))
    evidence = [
        {
            "evidence_id": "ev_" + reason.lower(),
            "type": "policy_feature",
            "reason_code": reason,
            "values": {
                "observation_age_seconds": age,
                "zone_entries": predicted["zone_entries"],
                "route_cross_track_m": route_error,
                "communication": communication,
                "heartbeat_age_seconds": heartbeat_age,
            },
            "observed_at": stamp(track["last_time"]),
            "origin": "deterministic_demo_policy",
        }
        for reason in reasons
    ]
    if track.get("note"):
        evidence.append(
            {
                "evidence_id": "ev_operator_note",
                "type": "operator_note",
                "origin": "untrusted_operator_text",
                **track["note"],
            }
        )
    eligible = ["REQUEST_POSITION_UPDATE"] if quality in ("STALE", "LOST", "CONFLICT") else []
    if authorization != "AUTHORIZED":
        eligible += ["VERIFY_TRACK_IDENTITY", "CHECK_MISSION_RECORD"]
    if contact:
        eligible += ["ASK_KNOWN_OPERATOR"]
    if not eligible or "POSITION_UNCERTAINTY_NEAR_ZONE" in reasons:
        eligible += ["REQUEST_POSITION_UPDATE"]
    entry_times = [
        v for z, v in predicted["zone_entries"].items() if z in relevant and v is not None and v > 0
    ]
    deadline = min(entry_times, default=30)
    eligible = list(
        dict.fromkeys(e for e in eligible if policy.evidence_response_seconds.get(e, 0) <= deadline)
    )
    previous = track.get("assessment")
    result = Assessment(
        assessment_id="assess_" + uuid.uuid4().hex,
        session_id=session["session_id"],
        track_id=track_id,
        core_revision=previous["core_revision"] if previous else 1,
        assessed_at=stamp(now),
        last_observed_at=stamp(track["last_time"]),
        policy_version=policy.version,
        registry_version=policy.registry_version,
        source={
            "applied_event_id": track["event_id"],
            "source_id": track["source_id"],
            "observation_age_seconds": age,
            "synthetic_data": True,
            "accepted_observations": track["accepted_count"],
            "rejected_outliers": track["outliers"],
        },
        estimate={
            "x_m": float(mean[0]),
            "y_m": float(mean[1]),
            "vx_mps": float(mean[2]),
            "vy_mps": float(mean[3]),
            "speed_mps": float(np.linalg.norm(mean[2:])),
            "covariance": covariance.tolist(),
            "velocity_established": track["velocity_established"],
            "estimated_at": stamp(now),
        },
        authorization={
            "status": authorization,
            "mission_id": mission_id,
            "claimed_vehicle_id": track.get("claimed_vehicle_id"),
            "binding_provenance": {**binding, "time": stamp(binding["time"])} if binding else None,
            "per_zone_permissions": permissions,
        },
        risk={
            "current_band": risk,
            "reason_codes": reasons,
            "historical_incident_maximum": None,
            "calibrated": False,
        },
        forecast=predicted,
        recommendation={
            "primary_action": action,
            "human_action_required": action != "MONITOR",
            "advisory": True,
            "deterministic_explanation": f"{authorization}; {risk}. "
            + "; ".join(reasons)
            + f". Position age {age:.1f}s. Route distance "
            + (f"{route_error:.1f}m." if route_error is not None else "unavailable."),
            "evidence_ids": [e["evidence_id"] for e in evidence],
            "eligible_next_evidence": eligible,
            "ranking_method": "heuristic",
            "reassess_by": stamp(now + min(3, deadline)),
        },
        evidence=evidence,
        incident=None,
        capability={
            "data_quality": quality,
            "source_health": source_health,
            "core_health": "READY",
            "storage_health": "AVAILABLE",
            "ai_status": "OFF"
            if settings.ai_provider == "off"
            else "MOCK"
            if settings.ai_provider == "fake"
            else "READY",
        },
        ai_enrichment=None,
    ).model_dump(mode="json")
    digest = semantic_digest(result, track.get("note_revision", 0), session["generation"])
    if previous and track.get("digest") != digest:
        result["core_revision"] += 1
    elif previous:
        result["ai_enrichment"] = previous.get("ai_enrichment")
    track["digest"] = digest
    track["assessment"] = result
    return result
