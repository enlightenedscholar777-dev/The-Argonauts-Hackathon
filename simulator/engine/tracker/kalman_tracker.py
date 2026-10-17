"""
Level 2 — Kalman / EKF track state and estimator skeleton.

Implements a 6-state constant-velocity Kalman filter:
    state = [x, y, depth, vx, vy, vz]

For the hackathon this is a hand-rolled linear KF; swap in Stone Soup's
``KalmanPredictor`` + ``KalmanUpdater`` for a production implementation.

References
----------
- Stone Soup KF tutorial: https://stonesoup.readthedocs.io/en/latest/auto_tutorials/01_KalmanFilterTutorial.html
- structure.md — "Kalman Filter; Extended Kalman Filter when the measurement
  model requires it"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np

from simulator.data_models.observation import (
    BearingRange,
    MeasurementType,
    Observation,
    Position,
)


# ---------------------------------------------------------------------------
# Track state
# ---------------------------------------------------------------------------

@dataclass
class TrackState:
    """
    Current estimate for one tracked contact.

    ``x``   : state vector [x, y, depth, vx, vy, vz]  (metres, m/s)
    ``P``   : 6×6 state covariance matrix
    ``updated_at`` : wall-clock time of the last measurement update
    ``vehicle_id`` : set only when cooperative identity is verified
    """
    track_id:   str
    x:          np.ndarray = field(default_factory=lambda: np.zeros(6))
    P:          np.ndarray = field(default_factory=lambda: np.eye(6) * 100.0)
    updated_at: Optional[datetime] = None
    vehicle_id: Optional[str] = None

    @property
    def position(self) -> Tuple[float, float, float]:
        return float(self.x[0]), float(self.x[1]), float(self.x[2])

    @property
    def velocity(self) -> Tuple[float, float, float]:
        return float(self.x[3]), float(self.x[4]), float(self.x[5])

    @property
    def position_uncertainty_m(self) -> float:
        """1-sigma positional uncertainty (horizontal, metres)."""
        return float(math.sqrt(self.P[0, 0] + self.P[1, 1]))


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

# Process noise acceleration standard deviation (m/s²)
_Q_SIGMA = 0.1


def _make_F(dt: float) -> np.ndarray:
    """Constant-velocity state transition matrix."""
    F = np.eye(6)
    F[0, 3] = dt
    F[1, 4] = dt
    F[2, 5] = dt
    return F


def _make_Q(dt: float, sigma: float = _Q_SIGMA) -> np.ndarray:
    """Discrete-time process noise for constant-velocity model."""
    q = sigma ** 2
    dt2, dt3 = dt ** 2, dt ** 3
    Q = np.zeros((6, 6))
    for i in range(3):
        Q[i,   i  ] = q * dt3 / 3
        Q[i,   i+3] = q * dt2 / 2
        Q[i+3, i  ] = q * dt2 / 2
        Q[i+3, i+3] = q * dt
    return Q


class KalmanTracker:
    """
    Manages a collection of TrackStates.

    ``update(obs)`` applies a prediction step (if ``dt`` > 0) and a
    measurement update for Position observations.  Bearing-only observations
    invoke the placeholder EKF path (TODO: full linearisation).

    Track initialisation: the first observation for an unknown track_id
    creates a new TrackState seeded from the measurement.
    """

    def __init__(self) -> None:
        self._tracks: Dict[str, TrackState] = {}

    # ------------------------------------------------------------------
    @property
    def tracks(self) -> Dict[str, TrackState]:
        return dict(self._tracks)

    # ------------------------------------------------------------------
    def update(self, obs: Observation) -> Optional[TrackState]:
        """
        Process one accepted Observation.

        Returns the updated (or newly created) TrackState, or None if the
        observation type is not yet handled by the tracker.
        """
        tid = obs.track_id
        if tid is None:
            return None   # cannot track without an ID

        track = self._tracks.get(tid)
        now   = obs.observed_at or obs.received_at

        if obs.measurement_type == MeasurementType.POSITION_3D and isinstance(obs.value, Position):
            return self._update_position(track, tid, obs.value, now, obs.vehicle_id)

        if obs.measurement_type == MeasurementType.POSITION_2D and isinstance(obs.value, Position):
            return self._update_position(track, tid, obs.value, now, obs.vehicle_id, surface=True)

        if obs.measurement_type in (MeasurementType.RANGE_BEARING, MeasurementType.BEARING_ONLY):
            return self._update_bearing(track, tid, obs.value, now)

        return track   # unsupported type — return current state unchanged

    # ------------------------------------------------------------------
    def _update_position(
        self,
        track: Optional[TrackState],
        tid: str,
        pos: Position,
        now: Optional[datetime],
        vehicle_id: Optional[str] = None,
        surface: bool = False,
    ) -> TrackState:

        z = np.array([pos.x, pos.y, pos.depth if pos.depth is not None else 0.0])
        # Measurement noise
        sx = pos.sigma_x or 5.0
        sy = pos.sigma_y or 5.0
        sz = pos.sigma_depth or (0.1 if not surface else 0.0)
        R  = np.diag([sx**2, sy**2, sz**2])
        # Observation matrix (position rows only)
        H  = np.zeros((3, 6))
        H[0, 0] = H[1, 1] = H[2, 2] = 1.0

        if track is None:
            # Initialise
            x = np.zeros(6)
            x[:3] = z
            P = np.block([
                [R,           np.zeros((3, 3))],
                [np.zeros((3, 3)), np.eye(3) * 1.0],
            ])
            track = TrackState(track_id=tid, x=x, P=P, updated_at=now)
            self._tracks[tid] = track
        else:
            # Predict
            dt = (now - track.updated_at).total_seconds() if now and track.updated_at else 0.0
            F  = _make_F(max(dt, 0.0))
            Q  = _make_Q(max(dt, 0.0))
            track.x = F @ track.x
            track.P = F @ track.P @ F.T + Q

            # Update (standard KF)
            y  = z - H @ track.x
            S  = H @ track.P @ H.T + R
            K  = track.P @ H.T @ np.linalg.inv(S)
            track.x = track.x + K @ y
            track.P = (np.eye(6) - K @ H) @ track.P
            track.updated_at = now

        if vehicle_id:
            track.vehicle_id = vehicle_id

        return track

    # ------------------------------------------------------------------
    def _update_bearing(
        self,
        track: Optional[TrackState],
        tid: str,
        br: BearingRange,
        now: Optional[datetime],
    ) -> TrackState:
        """
        Placeholder for EKF bearing-only / range-bearing update.

        A bearing-only observation preserves the measurement limit —
        it does not synthesize a full position.

        TODO: implement full EKF Jacobian linearisation or a particle filter.
        """
        if track is None:
            # Cannot initialise from bearing only without prior — create degenerate state
            x = np.zeros(6)
            P = np.eye(6) * 1000.0   # high initial uncertainty
            track = TrackState(track_id=tid, x=x, P=P, updated_at=now)
            self._tracks[tid] = track
        # Inflate uncertainty slightly each step until a position measurement arrives
        track.P += np.eye(6) * (_Q_SIGMA ** 2)
        return track
