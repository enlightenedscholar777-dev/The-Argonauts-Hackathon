"""
Level 2 — Trajectory predictor.

Uses a constant-velocity motion model plus sampled rollouts to estimate
possible future paths and test for zone boundary intersections.

structure.md: "Constant-velocity motion model + sampled trajectory rollouts
→ Possible future paths, zone overlap, conditional time-to-boundary"
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from simulator.data_models.records import Zone
from simulator.engine.tracker.kalman_tracker import TrackState


# ---------------------------------------------------------------------------
# Prediction output
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryForecast:
    """
    Future-path envelope for one track.

    ``samples``      : list of (x, y, depth) trajectories; each is a list of
                       time-step positions  [ [(x,y,z), …], … ]
    ``zone_hits``    : zones whose interior is entered by ≥ ``hit_threshold``
                       fraction of samples, with estimated time-to-entry
    ``horizon_s``    : forecast horizon (seconds)
    ``uncertain``    : True when positional uncertainty is already large at t=0
    """
    track_id:    str
    samples:     List[List[Tuple[float, float, float]]] = field(default_factory=list)
    zone_hits:   List["ZoneHit"]                        = field(default_factory=list)
    horizon_s:   float                                  = 0.0
    uncertain:   bool                                   = False


@dataclass
class ZoneHit:
    zone_id:       str
    zone_name:     str
    fraction:      float               # fraction of samples that enter
    earliest_s:    Optional[float]     # earliest hit time among samples (s)
    latest_s:      Optional[float]     # latest hit time among samples (s)


# ---------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------

class TrajectoryPredictor:
    """
    Generates Monte-Carlo trajectory rollouts from a TrackState.

    Parameters
    ----------
    horizon_s       : how far ahead to project (seconds)
    dt_s            : time step between samples (seconds)
    n_samples       : number of Monte-Carlo trajectories
    hit_threshold   : minimum sample fraction to report a zone hit
    uncertainty_cap : uncertainty (m) above which ``uncertain`` flag is set
    """

    def __init__(
        self,
        horizon_s:       float = 120.0,
        dt_s:            float = 5.0,
        n_samples:       int   = 50,
        hit_threshold:   float = 0.2,
        uncertainty_cap: float = 50.0,
    ) -> None:
        self.horizon_s       = horizon_s
        self.dt_s            = dt_s
        self.n_samples       = n_samples
        self.hit_threshold   = hit_threshold
        self.uncertainty_cap = uncertainty_cap

    # ------------------------------------------------------------------
    def forecast(self, track: TrackState, zones: List[Zone]) -> TrajectoryForecast:
        """
        Produce a trajectory forecast for ``track`` over ``zones``.

        Each sample draws an initial state from a Gaussian matching ``track.x``
        and ``track.P``, then advances it with the constant-velocity model
        corrupted by small process noise.
        """
        steps = max(1, int(self.horizon_s / self.dt_s))
        uncertain = track.position_uncertainty_m > self.uncertainty_cap

        # Hit counters: zone_id → [(sample_hit: bool, first_hit_time: float | None)]
        hit_records: dict[str, list] = {z.zone_id: [] for z in zones}

        all_samples: List[List[Tuple[float, float, float]]] = []

        for _ in range(self.n_samples):
            # Sample initial state from track distribution
            try:
                state = np.random.multivariate_normal(track.x, track.P)
            except np.linalg.LinAlgError:
                state = track.x.copy()

            path: List[Tuple[float, float, float]] = []
            zone_hit_time: dict[str, Optional[float]] = {z.zone_id: None for z in zones}

            for step in range(steps):
                t_s = (step + 1) * self.dt_s
                # Constant-velocity advance with small noise
                state[0] += state[3] * self.dt_s + random.gauss(0, 0.1)
                state[1] += state[4] * self.dt_s + random.gauss(0, 0.1)
                state[2] += state[5] * self.dt_s + random.gauss(0, 0.05)

                x, y, z_pos = float(state[0]), float(state[1]), float(state[2])
                path.append((x, y, z_pos))

                for zone in zones:
                    if zone_hit_time[zone.zone_id] is None and zone.contains_point(x, y):
                        zone_hit_time[zone.zone_id] = t_s

            all_samples.append(path)

            for zone in zones:
                zid = zone.zone_id
                hit_time = zone_hit_time.get(zid)
                hit_records[zid].append((hit_time is not None, hit_time))

        # Aggregate zone hits
        zone_hits: List[ZoneHit] = []
        for zone in zones:
            records  = hit_records[zone.zone_id]
            fraction = sum(1 for hit, _ in records if hit) / self.n_samples
            if fraction >= self.hit_threshold:
                times = [t for _, t in records if t is not None]
                zone_hits.append(ZoneHit(
                    zone_id    = zone.zone_id,
                    zone_name  = zone.name,
                    fraction   = fraction,
                    earliest_s = min(times) if times else None,
                    latest_s   = max(times) if times else None,
                ))

        return TrajectoryForecast(
            track_id  = track.track_id,
            samples   = all_samples,
            zone_hits = zone_hits,
            horizon_s = self.horizon_s,
            uncertain = uncertain,
        )
