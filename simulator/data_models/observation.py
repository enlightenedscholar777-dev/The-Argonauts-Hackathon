"""
Level 1 — Observation record.

Every sensor reading is stored as an Observation.  Fields follow the
evidence-package specification in structure.md:

    Observation ID, source, measurement type/value, units, coordinate frame,
    observed time, received time, uncertainty.

An unknown contact may carry a track_id while vehicle_id remains None.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MeasurementType(str, Enum):
    """Broad family of what a sensor measured."""
    POSITION_3D   = "position_3d"       # x, y, depth  (harbour frame)
    POSITION_2D   = "position_2d"       # x, y         (surface / AIS)
    BEARING_ONLY  = "bearing_only"      # angle from source, no range
    RANGE_BEARING = "range_bearing"     # sonar detection
    TELEMETRY     = "telemetry"         # robot health bundle
    ACOUSTIC      = "acoustic"          # hydrophone sound event
    ENVIRONMENT   = "environment"       # current, wind, tide …
    OPERATOR_NOTE = "operator_note"     # free-text human report


class ValueOrigin(str, Enum):
    """How the value was obtained."""
    MEASURED  = "measured"   # direct sensor reading
    REPORTED  = "reported"   # externally reported (e.g. AIS self-report)
    DERIVED   = "derived"    # computed from other observations


class SensorType(str, Enum):
    SONAR      = "sonar"
    HYDROPHONE = "hydrophone"
    USBL       = "usbl"
    AUV_TELEM  = "auv_telemetry"
    ROV_TELEM  = "rov_telemetry"
    AIS        = "ais"
    RADAR      = "radar"
    CAMERA     = "camera"
    ENV_STATION = "env_station"
    HUMAN      = "human"


@dataclass
class Position:
    """Position in the common harbour reference frame (metres, optional depth)."""
    x: float                    # east  (m)
    y: float                    # north (m)
    depth: Optional[float] = None   # positive = below surface (m)
    frame: str = "harbour_local"

    # 1-sigma uncertainty ellipse semi-axes (m); None = not available
    sigma_x: Optional[float] = None
    sigma_y: Optional[float] = None
    sigma_depth: Optional[float] = None


@dataclass
class BearingRange:
    """Sonar-style measurement: bearing (deg, true) and optional range (m)."""
    bearing_deg: float
    range_m: Optional[float] = None
    # source position at measurement time
    source_x: Optional[float] = None
    source_y: Optional[float] = None
    sigma_bearing_deg: Optional[float] = None
    sigma_range_m: Optional[float] = None


@dataclass
class Observation:
    """
    The canonical Level-1 record.

    ``value`` is a typed payload whose shape depends on ``measurement_type``.
    Acceptable payloads: Position, BearingRange, dict (telemetry / env), str (note).
    """

    # --- Identity and provenance ---
    observation_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id:         str = ""           # logical sensor / gateway ID
    sensor_type:       SensorType = SensorType.SONAR
    value_origin:      ValueOrigin = ValueOrigin.MEASURED

    # --- What was measured ---
    measurement_type:  MeasurementType = MeasurementType.POSITION_3D
    value:             object = None      # Position | BearingRange | dict | str

    # --- Timing ---
    observed_at:       Optional[datetime] = None   # when the sensor measured it
    received_at:       Optional[datetime] = None   # when we received the record

    # --- Contact labelling (may be unknown) ---
    track_id:          Optional[str] = None        # internal tracking ID (always assigned after ingest)
    vehicle_id:        Optional[str] = None        # cooperative / verified identity

    # --- Schema ---
    schema_version:    str = "1.0"

    def is_position_known(self) -> bool:
        return self.measurement_type in (
            MeasurementType.POSITION_3D,
            MeasurementType.POSITION_2D,
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Observation(id={self.observation_id[:8]}…, "
            f"source={self.source_id}, type={self.measurement_type.value}, "
            f"track={self.track_id}, vehicle={self.vehicle_id})"
        )
