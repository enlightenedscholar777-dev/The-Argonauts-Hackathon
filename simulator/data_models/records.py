"""
Level 1 — Mission, Zone, Environment, and Report records.

These companion records make up the rest of the structured evidence package
described in structure.md:

    Mission   — approved vehicle operations, permitted areas, schedules.
    Zone      — restricted / permitted areas with geometry and depth limits.
    Environment — measured or forecast conditions (NOAA CO-OPS style).
    Report    — operator / document text with attribution and version.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------

class MissionStatus(str, Enum):
    ACTIVE    = "active"
    COMPLETED = "completed"
    OVERDUE   = "overdue"      # missed expected contact
    CANCELLED = "cancelled"
    UNKNOWN   = "unknown"


@dataclass
class GeoBound:
    """Axis-aligned bounding box in the harbour reference frame (metres)."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    depth_min: Optional[float] = None   # None = surface operation
    depth_max: Optional[float] = None


@dataclass
class Mission:
    """
    A verified, approved vehicle operation.

    ``vehicle_id`` links to a cooperative vehicle.
    ``permitted_area`` is the authorised operating envelope.
    ``expected_contact_interval_s`` drives the missed-contact alert.
    """
    mission_id:                  str = field(default_factory=lambda: str(uuid.uuid4()))
    vehicle_id:                  str = ""
    operator_id:                 str = ""
    description:                 str = ""

    permitted_area:              Optional[GeoBound] = None
    valid_from:                  Optional[datetime] = None
    valid_until:                 Optional[datetime] = None
    expected_contact_interval_s: Optional[float] = None   # seconds between check-ins
    last_contact_at:             Optional[datetime] = None

    status:      MissionStatus = MissionStatus.UNKNOWN
    verified:    bool = False    # True only after authority check
    version:     int  = 1
    schema_version: str = "1.0"

    def is_active_at(self, t: datetime) -> bool:
        if self.valid_from and t < self.valid_from:
            return False
        if self.valid_until and t > self.valid_until:
            return False
        return self.status == MissionStatus.ACTIVE

    def contact_overdue(self, now: datetime) -> bool:
        if not self.expected_contact_interval_s or not self.last_contact_at:
            return False
        elapsed = (now - self.last_contact_at).total_seconds()
        return elapsed > self.expected_contact_interval_s


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------

class ZoneRestriction(str, Enum):
    RESTRICTED    = "restricted"    # requires explicit authorisation
    PROHIBITED    = "prohibited"    # no entry permitted
    AWARENESS     = "awareness"     # heightened monitoring only
    ANCHORAGE     = "anchorage"
    FAIRWAY       = "fairway"


@dataclass
class Zone:
    """
    A geographic area with operational constraints.

    Geometry is stored as an ordered polygon vertex list (harbour frame, metres).
    depth_min / depth_max are optional: None = applies at all depths.
    """
    zone_id:         str = field(default_factory=lambda: str(uuid.uuid4()))
    name:            str = ""
    restriction:     ZoneRestriction = ZoneRestriction.RESTRICTED
    polygon:         List[Tuple[float, float]] = field(default_factory=list)  # [(x,y), …]
    depth_min:       Optional[float] = None
    depth_max:       Optional[float] = None
    effective_from:  Optional[datetime] = None
    effective_until: Optional[datetime] = None
    version:         int = 1
    schema_version:  str = "1.0"

    def is_active_at(self, t: datetime) -> bool:
        if self.effective_from and t < self.effective_from:
            return False
        if self.effective_until and t > self.effective_until:
            return False
        return True

    def contains_point(self, x: float, y: float) -> bool:
        """Ray-casting point-in-polygon for convex/concave polygons."""
        verts = self.polygon
        n = len(verts)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = verts[i]
            xj, yj = verts[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class EnvMeasurementType(str, Enum):
    CURRENT_SPEED     = "current_speed"
    CURRENT_DIRECTION = "current_direction"
    WATER_LEVEL       = "water_level"
    WIND_SPEED        = "wind_speed"
    WIND_DIRECTION    = "wind_direction"
    VISIBILITY        = "visibility"
    WAVE_HEIGHT       = "wave_height"
    SALINITY          = "salinity"
    TEMPERATURE       = "temperature"


@dataclass
class EnvironmentRecord:
    """
    A single environmental measurement or forecast (NOAA CO-OPS style).

    ``is_forecast`` distinguishes a model prediction from an observation.
    ``station_id`` retains the originating station metadata.
    """
    record_id:        str = field(default_factory=lambda: str(uuid.uuid4()))
    station_id:       str = ""
    measurement_type: EnvMeasurementType = EnvMeasurementType.CURRENT_SPEED
    value:            float = 0.0
    units:            str = ""
    depth_m:          Optional[float] = None    # measurement depth; None = surface
    location_x:       Optional[float] = None    # harbour frame
    location_y:       Optional[float] = None
    observed_at:      Optional[datetime] = None
    is_forecast:      bool = False
    uncertainty:      Optional[float] = None
    schema_version:   str = "1.0"


# ---------------------------------------------------------------------------
# Report / Document
# ---------------------------------------------------------------------------

class ReportVerification(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED   = "verified"
    DISPUTED   = "disputed"


@dataclass
class Report:
    """
    An operator note, filed procedure, or harbour authority document.

    Authoritative records and unverified reports remain distinguishable via
    ``verification_status``.  Free text is treated as untrusted evidence;
    it should never directly grant permissions.
    """
    report_id:           str = field(default_factory=lambda: str(uuid.uuid4()))
    author_id:           str = ""
    source_description:  str = ""          # e.g. "harbour master", "AUV operator"
    text:                str = ""
    applicability:       str = ""          # free-text scope: "track T-001", "zone Z-A2" …
    verification_status: ReportVerification = ReportVerification.UNVERIFIED
    created_at:          Optional[datetime] = None
    version:             int = 1
    schema_version:      str = "1.0"

    def is_authoritative(self) -> bool:
        return self.verification_status == ReportVerification.VERIFIED
