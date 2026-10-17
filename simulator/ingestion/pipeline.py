"""
Level 1 — Ingestion pipeline.

Implements the seven processing steps from structure.md:

    Decode → Validate → Normalize coordinates → Preserve measurement limits
    → Handle timing → Attach provenance → Route to store.

``IngestionPipeline.process(raw_obs)`` returns an ``IngestResult`` that
carries either an accepted ``Observation`` or a rejection reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from simulator.data_models.observation import (
    BearingRange,
    MeasurementType,
    Observation,
    Position,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """Outcome of processing one raw Observation."""
    accepted:        bool
    observation:     Optional[Observation] = None
    rejection_reason: Optional[str] = None
    warnings:        List[str] = field(default_factory=list)

    @classmethod
    def ok(cls, obs: Observation, warnings: Optional[List[str]] = None) -> "IngestResult":
        return cls(accepted=True, observation=obs, warnings=warnings or [])

    @classmethod
    def reject(cls, reason: str) -> "IngestResult":
        return cls(accepted=False, rejection_reason=reason)


# ---------------------------------------------------------------------------
# Coordinate normaliser
# ---------------------------------------------------------------------------

class CoordinateNormalizer:
    """
    Converts compatible position observations into the common harbour frame.

    The harbour frame is a local flat-earth Cartesian frame (metres, east/north).
    For the simulator, raw observations already arrive in this frame; a real
    adapter would perform the geodetic conversion here (WGS-84 → local ENU).

    Important: bearing-only observations are *not* upgraded to positions here —
    the measurement limit is preserved.
    """

    def normalise(self, obs: Observation) -> Observation:
        """
        Return ``obs`` with ``value.frame`` set to ``"harbour_local"``.

        Currently a pass-through for simulated data.  Replace with a real
        projection (e.g. pyproj) when integrating live sensor feeds.
        """
        if isinstance(obs.value, Position) and obs.value.frame != "harbour_local":
            # TODO: apply geodetic → harbour-frame projection
            obs.value.frame = "harbour_local"   # placeholder
        return obs


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ObservationValidator:
    """
    Validates required fields, plausible ranges, and timestamp sanity.
    Returns (is_valid, reason_or_none, warning_list).
    """

    MAX_CLOCK_SKEW_S: float = 60.0   # reject observations >60 s in the future

    def validate(
        self,
        obs: Observation,
        now: datetime,
    ) -> tuple[bool, Optional[str], List[str]]:

        warnings: List[str] = []

        # --- Required fields ---
        if not obs.source_id:
            return False, "missing source_id", []
        if obs.value is None:
            return False, "missing value payload", []
        if obs.observed_at is None:
            return False, "missing observed_at timestamp", []

        # --- Timestamp sanity ---
        obs_time = obs.observed_at
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)

        now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        skew = (obs_time - now_aware).total_seconds()

        if skew > self.MAX_CLOCK_SKEW_S:
            return False, f"observation timestamp is {skew:.1f}s in the future", []

        if skew < -3600:
            warnings.append(f"observation is {-skew:.0f}s old — treating as late message")

        # --- Payload plausibility ---
        if isinstance(obs.value, Position):
            if not (-10_000 <= obs.value.x <= 10_000 and -10_000 <= obs.value.y <= 10_000):
                warnings.append("position outside expected harbour bounds; check coordinate frame")
            if obs.value.depth is not None and not (-1000 <= obs.value.depth <= 0):
                warnings.append(f"unusual depth value: {obs.value.depth} m")

        if isinstance(obs.value, BearingRange):
            if not (0 <= obs.value.bearing_deg < 360):
                return False, f"bearing_deg out of range: {obs.value.bearing_deg}", []
            if obs.value.range_m is not None and obs.value.range_m < 0:
                return False, "range_m must be non-negative", []

        return True, None, warnings


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class IngestionPipeline:
    """
    Stateless processing pipeline for Level 1 Observations.

    ``process(obs)`` → ``IngestResult``

    Steps
    -----
    1. Decode     — ensure the observation has a concrete type (already done
                    by sensor adapters in the simulator; real adapters decode
                    raw bytes here).
    2. Validate   — check required fields, units, timestamps, plausible ranges.
    3. Normalize  — convert coordinates into the harbour frame; preserve
                    bearing-only observations as bearing-only.
    4. Timing     — store observation time and arrival time separately.
    5. Provenance — attach source ID, sensor type, value origin (already on
                    the Observation); record pipeline arrival time.
    6. Accept     — return the processed Observation.
    """

    def __init__(self) -> None:
        self._validator  = ObservationValidator()
        self._normaliser = CoordinateNormalizer()
        self._seen_ids: set[str] = set()   # duplicate detection

    # ------------------------------------------------------------------
    def process(self, obs: Observation, now: Optional[datetime] = None) -> IngestResult:
        wall = now or datetime.now(timezone.utc)

        # Step 1: Decode — no-op for typed simulator observations
        # (A real adapter would parse bytes → Observation here.)

        # Duplicate detection
        if obs.observation_id in self._seen_ids:
            return IngestResult.reject(f"duplicate observation_id {obs.observation_id}")
        self._seen_ids.add(obs.observation_id)

        # Step 2: Validate
        valid, reason, warnings = self._validator.validate(obs, wall)
        if not valid:
            return IngestResult.reject(reason or "validation failed")

        # Step 3 & 4: Normalise coordinates; set received_at if missing
        obs = self._normaliser.normalise(obs)
        if obs.received_at is None:
            obs.received_at = wall

        # Step 5: Provenance already on the Observation from the sensor adapter.
        # A future enhancement would stamp schema_version and pipeline version here.

        return IngestResult.ok(obs, warnings)

    # ------------------------------------------------------------------
    def process_batch(
        self,
        observations: List[Observation],
        now: Optional[datetime] = None,
    ) -> List[IngestResult]:
        wall = now or datetime.now(timezone.utc)
        return [self.process(o, wall) for o in observations]
