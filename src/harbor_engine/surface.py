"""Bounded CPU traffic analysis, separate from sonar identity/mission policy.

Constant-velocity closest approach, route cross-track distance and schedule delay
are analytical models, not trained ML or calibrated collision probabilities.
"""

import math

from shapely.geometry import LineString, Point


def xy(lon, lat):
    return (lon + 118.22) * 92500, (lat - 33.75) * 111320


def assess_surface(vessels, age_seconds=0):
    rows = []
    for vessel in vessels:
        position = xy(vessel["lon"], vessel["lat"])
        distance = LineString([xy(*p) for p in vessel["route"]]).distance(Point(position))
        reasons = []
        if age_seconds > 3:
            reasons.append("POSITION_LOST" if age_seconds > 10 else "POSITION_STALE")
        else:
            if distance > 140:
                reasons.append("OFF_PLANNED_ROUTE")
            if vessel["delay_s"] >= 30 and vessel["status"] not in ("BERTHED", "DEPARTED"):
                reasons.append("SCHEDULE_DELAY")
        rows.append(
            {
                "vessel_id": vessel["vessel_id"],
                "destination": vessel["destination"],
                "route_id": vessel["route_id"],
                "lon": vessel["lon"],
                "lat": vessel["lat"],
                "status": vessel["status"],
                "phase": vessel["phase"],
                "speed_mps": math.hypot(vessel["vx_mps"], vessel["vy_mps"]),
                "scheduled_arrival_s": vessel["scheduled_arrival_s"],
                "eta_s": vessel["eta_s"],
                "delay_s": vessel["delay_s"],
                "cross_track_m": round(distance, 1),
                "observation_age_seconds": age_seconds,
                "reason_codes": reasons,
                "encounters": [],
            }
        )
    if age_seconds <= 3:
        for i, a in enumerate(vessels):
            for j in range(i + 1, len(vessels)):
                b = vessels[j]
                if a["status"] == b["status"] == "BERTHED":
                    continue
                ax, ay = xy(a["lon"], a["lat"])
                bx, by = xy(b["lon"], b["lat"])
                rx, ry = bx - ax, by - ay
                vx, vy = b["vx_mps"] - a["vx_mps"], b["vy_mps"] - a["vy_mps"]
                vv = vx * vx + vy * vy
                closest_in = max(0.0, min(120.0, -(rx * vx + ry * vy) / vv)) if vv > 0.01 else 0.0
                separation = math.hypot(rx + vx * closest_in, ry + vy * closest_in)
                if separation < 120 and math.hypot(rx, ry) < 1500:
                    for own, other in ((i, j), (j, i)):
                        rows[own]["reason_codes"].append("CLOSE_APPROACH")
                        rows[own]["encounters"].append(
                            {
                                "vessel_id": vessels[other]["vessel_id"],
                                "closest_in_s": round(closest_in, 1),
                                "separation_m": round(separation, 1),
                            }
                        )
    for row in rows:
        reasons = row["reason_codes"] = sorted(set(row["reason_codes"]))
        if any(r.startswith("POSITION_") for r in reasons):
            action, level = "Request a fresh surface position report", "UNKNOWN"
        elif "CLOSE_APPROACH" in reasons:
            action, level = "Review the encounter and coordinate transit order", "HIGH"
        elif "OFF_PLANNED_ROUTE" in reasons:
            action, level = "Contact the vessel operator to verify the intended route", "ELEVATED"
        elif "SCHEDULE_DELAY" in reasons:
            action, level = "Review the berth queue and update the arrival schedule", "ELEVATED"
        else:
            action, level = "Continue monitoring the scheduled voyage", "LOW"
        row.update(recommendation=action, concern=level, advisory=True)
    return {
        "model": "surface_kinematics_v1",
        "synthetic_data": True,
        "calibrated": False,
        "assumptions": "120s constant-velocity CPA; 120m proximity, 140m route deviation and 30s delay thresholds are demo values. Turns, hull geometry, COLREGs, tides and braking are not modeled.",
        "vessels": rows,
        "alerts": sum(bool(r["reason_codes"]) for r in rows),
        "observations": len(rows),
        "pairs_evaluated": len(rows) * (len(rows) - 1) // 2,
    }
