"""Seed synthetic surface movement from the supplied CSV, never ground truth.

The dataset has identities, types and scheduling states, but no coordinates.
Paths are generated on the existing illustrative water lanes and are context,
not observations or engine authorization. All positions use the scenario clock.
"""

import copy
import csv
import math
import random
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, Polygon

from harbor_simulation.map_catalog import TERMINALS
from harbor_simulation.voyages import VOYAGE_ROUTES, locate, metres, route_length

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/long_beach_dataset_only/synthetic_surface_vessels.csv"
FALLBACK = Path(__file__).parent / "data/synthetic_surface_vessels.csv"


@lru_cache(maxsize=4)
def load_traffic(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    required = {"vessel_id", "vessel_type", "fictional_zone", "status", "timestamp"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Traffic CSV needs vessel_id, vessel_type, fictional_zone, status and timestamp.")
    # Each identity appears once in a scene; the earliest record seeds its profile.
    unique = {}
    for row in sorted(rows, key=lambda r: (r["timestamp"], r["vessel_id"])):
        unique.setdefault(row["vessel_id"], row)
    return list(unique.values()), len(rows)


class HarborTraffic:
    """Seeded voyage scheduler with berth dwell, directional lanes and separation.

    A scheduled vessel stays off-map until there is physical room to admit it.
    No random phase, endpoint bouncing, overtaking or wrapping through a berth.
    """

    separation_m = 120.0
    separation_px = 18.0

    def __init__(self, seed=42, count=32, scenario="Harbor approach", path=None):
        path = Path(path) if path else DATASET if DATASET.exists() else FALLBACK
        profiles, row_count = load_traffic(str(path))
        rng = random.Random(seed)
        profiles = list(profiles)
        rng.shuffle(profiles)
        self.scenario = scenario
        self.land = [Polygon(t["outline"]).buffer(6) for t in TERMINALS]
        self.metadata = {
            "source": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
            "records": row_count,
            "identities": len(profiles),
            "position_provenance": "Scheduled synthetic voyages; CSV contains no coordinates",
            "separation_m": self.separation_m,
            "route_count": len(VOYAGE_ROUTES),
        }
        self.vessels = []
        self.clock = 0
        for i, profile in enumerate(profiles[:count]):
            plan = VOYAGE_ROUTES[i % len(VOYAGE_ROUTES)]
            speed = {"cargo": 3.5, "passenger": 5.5, "tug": 4, "service": 4.5}.get(profile["vessel_type"], 4)
            vessel = dict(
                profile=profile,
                plan=plan,
                speed=speed,
                distance=0.0,
                phase="SCHEDULED",
                geo=None,
                anchor=None,
                heading=0.0,
                vx=0.0,
                vy=0.0,
                status="SCHEDULED",
                scheduled_start_s=(i // len(VOYAGE_ROUTES)) * 25,
                scheduled_arrival_s=0.0,
                arrival_s=None,
                departure_s=None,
                hold_reason="Awaiting channel admission",
                trail=[],
                atlas_trail=[],
            )
            # Warm-start active voyages throughout the harbor, without overlap.
            length = route_length(plan)
            preferred = length * (0.15 + 0.14 * (i // len(VOYAGE_ROUTES)))
            candidates = sorted(range(0, int(length), 60), key=lambda d: abs(d - preferred))
            for distance in candidates:
                if distance > length - 600 and any(
                    v["plan"]["route_id"] == plan["route_id"] and v["distance"] > length - 600
                    for v in self.vessels
                    if v["geo"]
                ):
                    continue
                geo, anchor, heading = self.position(vessel, distance, "INBOUND")
                if self.clear(geo, anchor):
                    vessel.update(
                        distance=float(distance),
                        geo=geo,
                        anchor=anchor,
                        heading=heading,
                        phase="INBOUND",
                        status="UNDERWAY",
                        hold_reason="",
                        scheduled_start_s=0,
                    )
                    break
            vessel["scheduled_arrival_s"] = (
                vessel["scheduled_start_s"] + (length - vessel["distance"]) / speed
            )
            self.vessels.append(vessel)
        self.initial = copy.deepcopy(self.vessels)

    def position(self, vessel, distance, phase):
        plan = vessel["plan"]
        length = route_length(plan)
        geo, anchor = locate(plan, distance)
        before, a = locate(plan, max(0, distance - 150))
        after, b = locate(plan, min(length, distance + 150))
        east, north = (after[0] - before[0]) * 92500, (after[1] - before[1]) * 111320
        norm, drawing = max(1e-6, math.hypot(east, north)), max(1e-6, math.dist(a, b))
        direction = -1 if phase == "OUTBOUND" else 1
        taper = min(1.0, max(0.0, (length - distance) / 140))
        # Keep opposing streams on separate sides; converge only at the berth.
        geo[0] += north / norm * 75 * direction * taper / 92500
        geo[1] -= east / norm * 75 * direction * taper / 111320
        anchor[0] += (b[1] - a[1]) / drawing * 11 * direction * taper
        anchor[1] -= (b[0] - a[0]) / drawing * 11 * direction * taper
        heading = math.degrees(math.atan2((b[1] - a[1]) * direction, (b[0] - a[0]) * direction))
        return geo, anchor, heading

    def clear(self, geo, anchor, own=None):
        if any(p.covers(Point(anchor)) for p in self.land):
            return False
        return all(
            v is own
            or v["geo"] is None
            or (
                metres(geo, v["geo"]) >= self.separation_m
                and math.dist(anchor, v["anchor"]) >= self.separation_px
            )
            for v in self.vessels
        )

    def tick(self):
        self.clock += 1
        for i, vessel in enumerate(self.vessels):
            previous = list(vessel["geo"]) if vessel["geo"] else None
            vessel.update(vx=0.0, vy=0.0)
            phase = vessel["phase"]
            if phase == "DEPARTED":
                continue
            disrupted = self.scenario == "Port operations disruption" and i % 4 == 0 and self.clock >= 10
            if disrupted and vessel["geo"]:
                vessel.update(status="HOLDING", hold_reason="Demo incident: movement suspended")
                continue
            if phase == "BERTHED":
                vessel.update(status="BERTHED", hold_reason="Scheduled berth service")
                if self.clock < vessel["departure_s"]:
                    continue
                vessel["phase"] = phase = "OUTBOUND"
            if phase == "SCHEDULED":
                if self.clock < vessel["scheduled_start_s"]:
                    continue
                geo, anchor, heading = self.position(vessel, 0, "INBOUND")
                if not self.clear(geo, anchor, vessel):
                    continue
                vessel.update(phase="INBOUND", geo=geo, anchor=anchor, heading=heading)
                phase = "INBOUND"
            length = route_length(vessel["plan"])
            distance = (
                min(length, vessel["distance"] + vessel["speed"])
                if phase == "INBOUND"
                else max(0.0, vessel["distance"] - vessel["speed"])
            )
            # Reserve the berth turning basin for one vessel until its departure
            # has cleared it. Followers stop upstream, leaving maneuvering room.
            if (
                phase == "INBOUND"
                and distance > length - 600
                and any(
                    v is not vessel
                    and v["geo"]
                    and v["plan"]["route_id"] == vessel["plan"]["route_id"]
                    and v["distance"] > length - 600
                    and (v["phase"] in ("BERTHED", "OUTBOUND") or v["distance"] > vessel["distance"])
                    for v in self.vessels
                )
            ):
                vessel.update(status="HOLDING", hold_reason="Berth turning basin reserved for another vessel")
                continue
            geo, anchor, heading = self.position(vessel, distance, phase)
            if not self.clear(geo, anchor, vessel):
                vessel.update(status="HOLDING", hold_reason="Waiting for channel / berth separation")
                continue
            vessel.update(
                distance=distance, geo=geo, anchor=anchor, heading=heading, status="UNDERWAY", hold_reason=""
            )
            if previous:
                vessel.update(vx=(geo[0] - previous[0]) * 92500, vy=(geo[1] - previous[1]) * 111320)
            if phase == "INBOUND" and distance >= length:
                vessel.update(
                    phase="BERTHED",
                    status="BERTHED",
                    arrival_s=self.clock,
                    departure_s=self.clock + 60,
                    hold_reason="Scheduled berth service",
                    vx=0.0,
                    vy=0.0,
                )
            elif phase == "OUTBOUND" and distance <= 0:
                vessel.update(phase="DEPARTED", status="DEPARTED", geo=None, anchor=None, vx=0.0, vy=0.0)
            if vessel["geo"]:
                vessel["trail"] = (vessel["trail"] + [list(vessel["geo"])])[-12:]
                vessel["atlas_trail"] = (vessel["atlas_trail"] + [list(vessel["anchor"])])[-12:]

    def sample(self, elapsed):
        elapsed = max(0, int(elapsed))
        if elapsed < self.clock:
            self.vessels = copy.deepcopy(self.initial)
            self.clock = 0
        while self.clock < elapsed:
            self.tick()
        result = []
        for vessel in self.vessels:
            profile, plan = vessel["profile"], vessel["plan"]
            remaining = (
                route_length(plan) - vessel["distance"]
                if vessel["phase"] != "OUTBOUND"
                else vessel["distance"]
            )
            eta = (
                elapsed + remaining / vessel["speed"]
                if vessel["phase"] in ("INBOUND", "OUTBOUND", "SCHEDULED")
                else vessel["arrival_s"]
            )
            result.append(
                dict(
                    vessel_id=profile["vessel_id"],
                    vessel_type=profile["vessel_type"],
                    sector=profile["fictional_zone"],
                    source_status=profile["status"],
                    status=vessel["status"],
                    phase=vessel["phase"],
                    route_id=plan["route_id"],
                    destination=plan["destination"],
                    route=plan["geo"],
                    atlas_route=plan["atlas"],
                    scheduled_arrival_s=round(vessel["scheduled_arrival_s"], 1),
                    eta_s=round(eta, 1) if eta is not None else None,
                    delay_s=round(
                        max(0, (vessel["arrival_s"] or eta or 0) - vessel["scheduled_arrival_s"]), 1
                    )
                    if vessel["phase"] != "OUTBOUND"
                    else 0.0,
                    hold_reason=vessel["hold_reason"],
                    speed_mps=math.hypot(vessel["vx"], vessel["vy"]),
                    vx_mps=vessel["vx"],
                    vy_mps=vessel["vy"],
                    name=f"{profile['vessel_id']} · {plan['destination']} · {vessel['phase']} / {vessel['status']}\nScheduled synthetic voyage · {vessel['hold_reason']}",
                    lon=vessel["geo"][0] if vessel["geo"] else None,
                    lat=vessel["geo"][1] if vessel["geo"] else None,
                    anchor=vessel["anchor"],
                    heading=vessel["heading"],
                    trail=vessel["trail"] or ([vessel["geo"]] * 2 if vessel["geo"] else []),
                    atlas_trail=vessel["atlas_trail"] or ([vessel["anchor"]] * 2 if vessel["anchor"] else []),
                )
            )
        return result
