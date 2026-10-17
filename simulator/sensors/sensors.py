"""
Sensor simulators — Level 1 data sources.

Each sensor subclass produces a stream of Observations from a parametric
scenario description.  Real sensor adapters would replace these classes while
keeping the same ``generate()`` interface.

Usage
-----
    sensor = SonarSensor(source_id="sonar-01", x=0.0, y=0.0)
    for obs in sensor.generate(scenario_clock):
        pipeline.ingest(obs)
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Generator, List, Optional, Tuple

from simulator.data_models.observation import (
    BearingRange,
    MeasurementType,
    Observation,
    Position,
    SensorType,
    ValueOrigin,
)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseSensor(ABC):
    """
    Abstract sensor adapter.

    ``generate()`` is a generator that yields Observations given a wall-clock
    tick.  Subclasses must implement ``_produce()``.
    """

    def __init__(
        self,
        source_id: str,
        sensor_type: SensorType,
        noise_sigma: float = 1.0,
        dropout_prob: float = 0.0,   # probability of producing nothing on a tick
        rng: Optional[random.Random] = None,
    ) -> None:
        self.source_id    = source_id
        self.sensor_type  = sensor_type
        self.noise_sigma  = noise_sigma
        self.dropout_prob = dropout_prob
        self.rng = rng if rng is not None else random

    def generate(self, now: datetime) -> List[Observation]:
        """Return 0-N observations for the given simulation timestamp."""
        if self.rng.random() < self.dropout_prob:
            return []    # simulated sensor dropout
        return self._produce(now)

    @abstractmethod
    def _produce(self, now: datetime) -> List[Observation]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    def _jitter(self, value: float, sigma: Optional[float] = None) -> float:
        return value + self.rng.gauss(0.0, sigma if sigma is not None else self.noise_sigma)


# ---------------------------------------------------------------------------
# Sonar — detects contacts as bearing / range pairs
# ---------------------------------------------------------------------------

@dataclass
class ContactSpec:
    """Specification for a single simulated underwater contact."""
    track_id:    str
    # linear motion: start position + velocity (m/s)
    x0: float = 0.0
    y0: float = 0.0
    depth0: float = -10.0
    vx: float = 0.5        # m/s east
    vy: float = 0.2        # m/s north
    vehicle_id: Optional[str] = None   # None = unknown cooperative identity


class SonarSensor(BaseSensor):
    """
    Fixed seabed / ship-mounted sonar.

    Produces bearing-only or range-bearing detections for each contact that
    falls within ``detection_range_m``.  A detection does *not* imply identity.
    """

    def __init__(
        self,
        source_id: str,
        x: float,
        y: float,
        contacts: Optional[List[ContactSpec]] = None,
        detection_range_m: float = 500.0,
        bearing_sigma_deg: float = 2.0,
        range_sigma_m: float = 5.0,
        provide_range: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(source_id, SensorType.SONAR, **kwargs)
        self.x                  = x
        self.y                  = y
        self.contacts           = contacts or []
        self.detection_range_m  = detection_range_m
        self.bearing_sigma_deg  = bearing_sigma_deg
        self.range_sigma_m      = range_sigma_m
        self.provide_range      = provide_range
        self._start: Optional[datetime] = None

    def _produce(self, now: datetime) -> List[Observation]:
        if self._start is None:
            self._start = now

        results: List[Observation] = []
        elapsed = (now - self._start).total_seconds()

        for contact in self.contacts:
            cx = contact.x0 + contact.vx * elapsed
            cy = contact.y0 + contact.vy * elapsed

            dx, dy = cx - self.x, cy - self.y
            true_range = math.hypot(dx, dy)
            if true_range > self.detection_range_m:
                continue   # out of detection range

            true_bearing = math.degrees(math.atan2(dx, dy)) % 360

            noisy_bearing = self._jitter(true_bearing, self.bearing_sigma_deg)
            noisy_range   = self._jitter(true_range,   self.range_sigma_m) if self.provide_range else None

            measurement = BearingRange(
                bearing_deg=noisy_bearing,
                range_m=noisy_range,
                source_x=self.x,
                source_y=self.y,
                sigma_bearing_deg=self.bearing_sigma_deg,
                sigma_range_m=self.range_sigma_m if self.provide_range else None,
            )

            results.append(Observation(
                source_id=self.source_id,
                sensor_type=SensorType.SONAR,
                value_origin=ValueOrigin.MEASURED,
                measurement_type=(
                    MeasurementType.RANGE_BEARING if self.provide_range
                    else MeasurementType.BEARING_ONLY
                ),
                value=measurement,
                observed_at=now,
                received_at=now,
                track_id=contact.track_id,
                # NOTE: vehicle_id intentionally NOT set here — sonar does
                #       not establish cooperative identity.
            ))

        return results


# ---------------------------------------------------------------------------
# Cooperative AUV / ROV telemetry
# ---------------------------------------------------------------------------

class CooperativeTelemetrySensor(BaseSensor):
    """
    Simulates AUV/ROV reporting its own position and health via acoustic modem.

    ``vehicle_id`` is set because the vehicle identifies itself; the policy
    engine still has to verify the mission association.
    """

    def __init__(
        self,
        source_id: str,
        vehicle_id: str,
        x0: float,
        y0: float,
        depth0: float,
        vx: float = 0.3,
        vy: float = 0.1,
        position_sigma_m: float = 3.0,
        report_interval_s: float = 30.0,
        **kwargs,
    ) -> None:
        super().__init__(source_id, SensorType.AUV_TELEM, **kwargs)
        self.vehicle_id        = vehicle_id
        self.x0, self.y0       = x0, y0
        self.depth0            = depth0
        self.vx, self.vy       = vx, vy
        self.position_sigma_m  = position_sigma_m
        self.report_interval_s = report_interval_s
        self._start: Optional[datetime] = None
        self._last_report: Optional[datetime] = None

    def _produce(self, now: datetime) -> List[Observation]:
        if self._start is None:
            self._start = now

        # Only emit on the reporting cadence
        if self._last_report is not None:
            elapsed_since = (now - self._last_report).total_seconds()
            if elapsed_since < self.report_interval_s:
                return []

        self._last_report = now
        elapsed = (now - self._start).total_seconds()

        pos = Position(
            x     = self._jitter(self.x0 + self.vx * elapsed, self.position_sigma_m),
            y     = self._jitter(self.y0 + self.vy * elapsed, self.position_sigma_m),
            depth = self._jitter(self.depth0, 0.5),
            sigma_x=self.position_sigma_m,
            sigma_y=self.position_sigma_m,
            sigma_depth=0.5,
        )

        return [Observation(
            source_id=self.source_id,
            sensor_type=SensorType.AUV_TELEM,
            value_origin=ValueOrigin.REPORTED,
            measurement_type=MeasurementType.POSITION_3D,
            value=pos,
            observed_at=now,
            received_at=now,
            track_id=self.vehicle_id,     # known cooperative — track_id matches vehicle
            vehicle_id=self.vehicle_id,
        )]


# ---------------------------------------------------------------------------
# AIS — surface vessel self-reports
# ---------------------------------------------------------------------------

class AISSensor(BaseSensor):
    """
    Simulates AIS transponder messages from a surface vessel.

    AIS provides surface traffic context; it is *not* underwater detection.
    """

    def __init__(
        self,
        source_id: str,
        mmsi: str,
        vessel_name: str,
        x0: float,
        y0: float,
        course_deg: float,
        speed_kts: float,
        report_interval_s: float = 10.0,
        **kwargs,
    ) -> None:
        super().__init__(source_id, SensorType.AIS, **kwargs)
        self.mmsi              = mmsi
        self.vessel_name       = vessel_name
        self.x0, self.y0       = x0, y0
        self.course_deg        = course_deg
        self.speed_ms          = speed_kts * 0.5144  # knots → m/s
        self.report_interval_s = report_interval_s
        self._start: Optional[datetime] = None
        self._last_report: Optional[datetime] = None

    def _produce(self, now: datetime) -> List[Observation]:
        if self._start is None:
            self._start = now
        if self._last_report is not None:
            if (now - self._last_report).total_seconds() < self.report_interval_s:
                return []
        self._last_report = now

        elapsed = (now - self._start).total_seconds()
        rad = math.radians(self.course_deg)
        pos = Position(
            x = self.x0 + self.speed_ms * math.sin(rad) * elapsed,
            y = self.y0 + self.speed_ms * math.cos(rad) * elapsed,
        )

        return [Observation(
            source_id=self.source_id,
            sensor_type=SensorType.AIS,
            value_origin=ValueOrigin.REPORTED,
            measurement_type=MeasurementType.POSITION_2D,
            value=pos,
            observed_at=now,
            received_at=now,
            track_id=self.mmsi,
            vehicle_id=self.mmsi,   # AIS provides a claimed identity
        )]


# ---------------------------------------------------------------------------
# Environmental sensor
# ---------------------------------------------------------------------------

class EnvironmentalSensor(BaseSensor):
    """
    Periodically emits an EnvironmentRecord-shaped dict as an Observation.

    Real implementation would call the NOAA CO-OPS API; here we use a
    simple sinusoidal model for current speed.
    """

    def __init__(
        self,
        source_id: str,
        station_id: str,
        x: float,
        y: float,
        baseline_current_ms: float = 0.5,
        report_interval_s: float = 60.0,
        **kwargs,
    ) -> None:
        super().__init__(source_id, SensorType.ENV_STATION, **kwargs)
        self.station_id            = station_id
        self.x, self.y             = x, y
        self.baseline_current_ms   = baseline_current_ms
        self.report_interval_s     = report_interval_s
        self._start: Optional[datetime] = None
        self._last_report: Optional[datetime] = None

    def _produce(self, now: datetime) -> List[Observation]:
        if self._start is None:
            self._start = now
        if self._last_report is not None:
            if (now - self._last_report).total_seconds() < self.report_interval_s:
                return []
        self._last_report = now

        elapsed = (now - self._start).total_seconds()
        current_speed = self.baseline_current_ms + 0.2 * math.sin(elapsed / 600.0)

        payload = {
            "station_id":       self.station_id,
            "measurement_type": "current_speed",
            "value":            current_speed,
            "units":            "m/s",
            "location_x":       self.x,
            "location_y":       self.y,
        }

        return [Observation(
            source_id=self.source_id,
            sensor_type=SensorType.ENV_STATION,
            value_origin=ValueOrigin.MEASURED,
            measurement_type=MeasurementType.ENVIRONMENT,
            value=payload,
            observed_at=now,
            received_at=now,
        )]


# ---------------------------------------------------------------------------
# Operator note injector
# ---------------------------------------------------------------------------

class OperatorNoteInjector(BaseSensor):
    """
    Simulates a harbour officer entering free-text reports.

    Notes are treated as unverified evidence — they provide a hypothesis, not
    an authoritative relabelling.
    """

    def __init__(
        self,
        source_id: str,
        author_id: str,
        notes: Optional[List[Tuple[float, str]]] = None,  # [(elapsed_s, text), …]
        **kwargs,
    ) -> None:
        super().__init__(source_id, SensorType.HUMAN, **kwargs)
        self.author_id = author_id
        # Sorted by scheduled elapsed seconds
        self._notes = sorted(notes or [], key=lambda n: n[0])
        self._emitted: set = set()
        self._start: Optional[datetime] = None

    def _produce(self, now: datetime) -> List[Observation]:
        if self._start is None:
            self._start = now

        elapsed = (now - self._start).total_seconds()
        results: List[Observation] = []

        for i, (trigger_s, text) in enumerate(self._notes):
            if i in self._emitted:
                continue
            if elapsed >= trigger_s:
                self._emitted.add(i)
                results.append(Observation(
                    source_id=self.source_id,
                    sensor_type=SensorType.HUMAN,
                    value_origin=ValueOrigin.REPORTED,
                    measurement_type=MeasurementType.OPERATOR_NOTE,
                    value=text,
                    observed_at=now,
                    received_at=now,
                ))

        return results
