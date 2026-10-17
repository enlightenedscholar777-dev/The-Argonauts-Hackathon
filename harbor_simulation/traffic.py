"""Seed synthetic surface movement from the supplied CSV, never ground truth.

The dataset has identities, types and scheduling states, but no coordinates.
Paths are generated on the existing illustrative water lanes and are context,
not observations or engine authorization. All positions use the scenario clock.
"""

import csv
import math
import random
from functools import lru_cache
from pathlib import Path

from harbor_simulation.map_catalog import CONTEXT_LANES

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
    def __init__(self, seed=42, count=32, scenario="Harbor approach", path=None):
        path = Path(path) if path else DATASET if DATASET.exists() else FALLBACK
        profiles, row_count = load_traffic(str(path))
        rng = random.Random(seed)
        profiles = list(profiles)
        rng.shuffle(profiles)
        self.scenario = scenario
        self.metadata = {
            "source": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
            "records": row_count,
            "identities": len(profiles),
            "position_provenance": "Generated water-lane trajectories; CSV contains no coordinates",
        }
        self.vessels = []
        for i, profile in enumerate(profiles[:count]):
            # Interleave lanes so every scene has traffic throughout the harbor.
            lane = CONTEXT_LANES[i % len(CONTEXT_LANES)]
            speed = {"cargo": 3.5, "passenger": 7, "tug": 4, "service": 5}.get(profile["vessel_type"], 4)
            self.vessels.append(
                dict(
                    profile=profile,
                    lane=lane,
                    phase=rng.uniform(0, 2),
                    speed=speed * rng.uniform(0.85, 1.15),
                    hold=rng.randint(5, 18) if profile["status"] == "arrived" else 0,
                    lane_offset=(i // len(CONTEXT_LANES) % 3 - 1) * 10,
                )
            )

    def sample(self, elapsed):
        result = []
        for i, vessel in enumerate(self.vessels):
            profile, lane = vessel["profile"], vessel["lane"]
            start, end, a, b, _ = lane
            length = math.hypot((end[0] - start[0]) * 92500, (end[1] - start[1]) * 111320)
            disrupted = self.scenario == "Port operations disruption" and i % 4 == 0 and elapsed >= 10
            clock = min(elapsed, 10) if disrupted else elapsed

            def position(second):
                phase = (vessel["phase"] + max(0, second - vessel["hold"]) * vessel["speed"] / length) % 2
                fraction = phase if phase <= 1 else 2 - phase
                direction = 1 if phase < 1 else -1
                geo = [s + (e - s) * fraction for s, e in zip(start, end)]
                anchor = [s + (e - s) * fraction for s, e in zip(a, b)]
                drawing_length = math.dist(a, b)
                offset = vessel["lane_offset"]
                anchor[0] -= (b[1] - a[1]) / drawing_length * offset
                anchor[1] += (b[0] - a[0]) / drawing_length * offset
                # Small parallel lanes keep dense traffic legible in both views.
                east, north = (end[0] - start[0]) * 92500, (end[1] - start[1]) * 111320
                geo[0] -= north / length * offset * 2 / 92500
                geo[1] += east / length * offset * 2 / 111320
                return geo, anchor, direction

            geo, anchor, direction = position(clock)
            previous_geo, previous_anchor, _ = position(max(0, clock - 12))
            holding = disrupted or elapsed < vessel["hold"]
            result.append(
                dict(
                    vessel_id=profile["vessel_id"],
                    vessel_type=profile["vessel_type"],
                    sector=profile["fictional_zone"],
                    source_status=profile["status"],
                    status="HOLDING" if holding else "UNDERWAY",
                    speed_mps=0 if holding else vessel["speed"],
                    name=f"{profile['vessel_id']} · {profile['vessel_type']} · {'HOLDING' if holding else 'UNDERWAY'}\nGenerated motion from synthetic CSV profile · context only",
                    lon=geo[0],
                    lat=geo[1],
                    anchor=anchor,
                    heading=math.degrees(math.atan2((b[1] - a[1]) * direction, (b[0] - a[0]) * direction)),
                    trail=[previous_geo, geo],
                    atlas_trail=[previous_anchor, anchor],
                )
            )
        return result
