"""
Simulator orchestrator — clock, scenario runner, and fault-injection panel.

Ties together:
  - A configurable simulation clock (real-time or accelerated)
  - A set of sensors producing observations each tick
  - The IngestionPipeline (Level 1)
  - The InMemoryJournal (Level 1 store)
  - The DecisionEngine (Level 2)
  - A fault-injection panel for demo scenarios (inference.md §11)

Usage
-----
    scenario = ScenarioConfig.demo()
    runner   = SimulatorRunner(scenario)
    runner.run(steps=60)            # 60 ticks
    runner.run_realtime(duration_s=120)  # wall-clock run

Fault injection
---------------
    runner.faults.drop_sensor("sonar-01")
    runner.faults.set_clock_jump(30.0)
    runner.faults.disable_ai()
    runner.faults.reset()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from simulator.data_models.records import Mission, Zone, ZoneRestriction
from simulator.engine.decision_engine import DecisionEngine
from simulator.ingestion.pipeline import IngestionPipeline
from simulator.journal.journal import InMemoryJournal
from simulator.output.decision_package import DecisionPackage
from simulator.sensors.sensors import (
    AISSensor,
    BaseSensor,
    ContactSpec,
    CooperativeTelemetrySensor,
    EnvironmentalSensor,
    OperatorNoteInjector,
    SonarSensor,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fault-injection panel
# ---------------------------------------------------------------------------

class FaultPanel:
    """
    Runtime fault injection for demo and resilience testing.

    inference.md §11: "Build a fault-injection panel into the simulator."
    Each fault can be toggled independently.
    """

    def __init__(self) -> None:
        self._dropped_sensors: set[str]  = set()
        self._clock_jump_s:    float     = 0.0
        self._ai_disabled:     bool      = False
        self._event_flood:     bool      = False
        self._replay_old_data: bool      = False

    def drop_sensor(self, source_id: str) -> None:
        """Simulate sensor dropout / disconnect."""
        self._dropped_sensors.add(source_id)
        logger.warning("[FAULT] Sensor dropped: %s", source_id)

    def restore_sensor(self, source_id: str) -> None:
        self._dropped_sensors.discard(source_id)
        logger.info("[FAULT CLEARED] Sensor restored: %s", source_id)

    def set_clock_jump(self, jump_s: float) -> None:
        """Inject a forward or backward clock jump (seconds)."""
        self._clock_jump_s = jump_s
        logger.warning("[FAULT] Clock jump: %+.1f s", jump_s)

    def disable_ai(self) -> None:
        self._ai_disabled = True
        logger.warning("[FAULT] AI branch disabled.")

    def enable_ai(self) -> None:
        self._ai_disabled = False
        logger.info("[FAULT CLEARED] AI branch re-enabled.")

    def enable_event_flood(self) -> None:
        """Simulate a burst of duplicate / high-rate observations."""
        self._event_flood = True
        logger.warning("[FAULT] Event flood enabled.")

    def disable_event_flood(self) -> None:
        self._event_flood = False

    def enable_replay_old_data(self) -> None:
        """Replay stale observations — should be rejected by the pipeline."""
        self._replay_old_data = True
        logger.warning("[FAULT] Old-data replay enabled.")

    def disable_replay_old_data(self) -> None:
        self._replay_old_data = False

    def reset(self) -> None:
        self._dropped_sensors.clear()
        self._clock_jump_s  = 0.0
        self._ai_disabled   = False
        self._event_flood   = False
        self._replay_old_data = False
        logger.info("[FAULT] All faults cleared.")

    # --- Accessors ---
    def is_dropped(self, source_id: str) -> bool:
        return source_id in self._dropped_sensors

    @property
    def clock_jump_s(self) -> float:
        return self._clock_jump_s

    @property
    def ai_disabled(self) -> bool:
        return self._ai_disabled

    @property
    def event_flood(self) -> bool:
        return self._event_flood

    @property
    def replay_old_data(self) -> bool:
        return self._replay_old_data


# ---------------------------------------------------------------------------
# Scenario configuration
# ---------------------------------------------------------------------------

@dataclass
class ScenarioConfig:
    """
    Parameters for a simulation run.

    The default ``demo()`` scenario matches the end-to-end example in
    structure.md: an unknown contact moves toward a restricted dock while
    a research operator reports a robot off course.
    """
    name:               str = "unnamed"
    tick_s:             float = 5.0          # simulation time per step
    missions:           List[Mission]  = field(default_factory=list)
    zones:              List[Zone]     = field(default_factory=list)
    sensors:            List[BaseSensor] = field(default_factory=list)
    response_window_s:  float = 60.0
    forecast_horizon_s: float = 120.0

    # ------------------------------------------------------------------
    @classmethod
    def demo(cls) -> "ScenarioConfig":
        """
        Canonical demo scenario from structure.md §end-to-end example.

        Contacts
        --------
        T-001  — unknown contact moving toward the restricted dock.
        AUV-01 — cooperative research AUV reporting its own position;
                  deviates from its permitted area mid-scenario.

        Zones
        -----
        Z-DOCK — restricted dock area.
        Z-RESEARCH — AUV operating zone.

        Sensors
        -------
        sonar-01   — fixed seabed sonar detecting T-001.
        telem-01   — AUV-01 telemetry gateway.
        ais-01     — surface support vessel.
        env-01     — harbour current station.
        notes-01   — operator note injector.
        """
        import datetime as _dt

        epoch = _dt.datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

        # --- Restricted dock zone ---
        dock_zone = Zone(
            zone_id="Z-DOCK",
            name="Restricted Dock Area",
            restriction=ZoneRestriction.RESTRICTED,
            polygon=[(150, 100), (300, 100), (300, 250), (150, 250)],
        )

        # --- Research operating zone ---
        research_zone = Zone(
            zone_id="Z-RESEARCH",
            name="AUV Research Zone",
            restriction=ZoneRestriction.AWARENESS,
            polygon=[(-100, -100), (100, -100), (100, 100), (-100, 100)],
        )

        # --- Mission for AUV-01 ---
        from simulator.data_models.records import GeoBound, MissionStatus
        mission = Mission(
            mission_id="M-AUV-01",
            vehicle_id="AUV-01",
            operator_id="OP-RESEARCH",
            description="Research survey — AUV operating zone",
            permitted_area=GeoBound(x_min=-100, y_min=-100, x_max=100, y_max=100),
            valid_from=epoch,
            valid_until=epoch + _dt.timedelta(hours=4),
            expected_contact_interval_s=60.0,
            last_contact_at=epoch,
            status=MissionStatus.ACTIVE,
            verified=True,
        )

        # --- Sensors ---
        unknown_contact = ContactSpec(
            track_id="T-001",
            x0=-200.0, y0=0.0, depth0=-15.0,
            vx=1.2, vy=0.4,   # heading toward the dock zone
        )

        sonar = SonarSensor(
            source_id="sonar-01",
            x=0.0, y=0.0,
            contacts=[unknown_contact],
            detection_range_m=600.0,
            provide_range=True,
            noise_sigma=1.0,
            dropout_prob=0.05,
        )

        auv_telem = CooperativeTelemetrySensor(
            source_id="telem-01",
            vehicle_id="AUV-01",
            x0=-50.0, y0=20.0, depth0=-8.0,
            vx=0.2, vy=0.05,
            report_interval_s=30.0,
            noise_sigma=1.0,
        )

        ais = AISSensor(
            source_id="ais-01",
            mmsi="123456789",
            vessel_name="SV-SUPPORT",
            x0=-500.0, y0=-100.0,
            course_deg=45.0,
            speed_kts=3.0,
            report_interval_s=10.0,
        )

        env_sensor = EnvironmentalSensor(
            source_id="env-01",
            station_id="STATION-HARBOUR-01",
            x=0.0, y=0.0,
            report_interval_s=60.0,
        )

        notes = OperatorNoteInjector(
            source_id="notes-01",
            author_id="OP-RESEARCH",
            notes=[
                (90.0,  "AUV-01 is deviating from planned route. Last comms 2 min ago."),
                (180.0, "Support vessel reports visual of unidentified object near dock approach."),
            ],
        )

        return cls(
            name="demo-scenario",
            tick_s=5.0,
            missions=[mission],
            zones=[dock_zone, research_zone],
            sensors=[sonar, auv_telem, ais, env_sensor, notes],
            response_window_s=60.0,
            forecast_horizon_s=120.0,
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class SimulatorRunner:
    """
    Drives a simulation scenario tick by tick.

    After each tick, the runner:
    1. Calls each sensor's ``generate(now)`` (respecting dropped-sensor faults).
    2. Passes raw observations through the ingestion pipeline.
    3. Commits accepted observations to the journal.
    4. Feeds each accepted observation to the decision engine.
    5. Emits a DecisionPackage for each track update.

    ``on_package`` is an optional callback invoked for every emitted package.
    """

    def __init__(
        self,
        config: ScenarioConfig,
        on_package: Optional[Callable[[DecisionPackage], None]] = None,
    ) -> None:
        self.config    = config
        self.faults    = FaultPanel()
        self.on_package = on_package or self._default_on_package

        self._pipeline = IngestionPipeline()
        self._journal  = InMemoryJournal()
        self._engine   = DecisionEngine(
            missions=config.missions,
            zones=config.zones,
            response_window_s=config.response_window_s,
            forecast_horizon_s=config.forecast_horizon_s,
        )
        self._sim_time: Optional[datetime] = None

    # ------------------------------------------------------------------
    def run(
        self,
        steps: int,
        start_time: Optional[datetime] = None,
    ) -> None:
        """
        Run the scenario for ``steps`` simulation ticks.

        ``start_time`` defaults to now (UTC).
        """
        self._sim_time = start_time or datetime.now(timezone.utc)

        for step in range(steps):
            self._tick(step)
            self._sim_time += timedelta(seconds=self.config.tick_s)

    # ------------------------------------------------------------------
    def run_realtime(
        self,
        duration_s: float,
        start_time: Optional[datetime] = None,
    ) -> None:
        """Run in real time, sleeping between ticks."""
        self._sim_time = start_time or datetime.now(timezone.utc)
        end_wall = time.monotonic() + duration_s
        step = 0

        while time.monotonic() < end_wall:
            t0 = time.monotonic()
            self._tick(step)
            step += 1
            elapsed = time.monotonic() - t0
            sleep = self.config.tick_s - elapsed
            if sleep > 0:
                time.sleep(sleep)
            self._sim_time += timedelta(seconds=self.config.tick_s)

    # ------------------------------------------------------------------
    def _tick(self, step: int) -> None:
        now = self._sim_time
        assert now is not None

        # Apply clock jump fault
        if self.faults.clock_jump_s:
            now = now + timedelta(seconds=self.faults.clock_jump_s)

        logger.debug("[TICK %d] sim_time=%s", step, now.isoformat())

        for sensor in self.config.sensors:
            # Respect dropped-sensor fault
            if self.faults.is_dropped(sensor.source_id):
                continue

            raw_observations = sensor.generate(now)

            # Event-flood fault: duplicate each observation
            if self.faults.event_flood:
                raw_observations = raw_observations + raw_observations

            for raw_obs in raw_observations:
                # Old-data replay fault: backdate the observation
                if self.faults.replay_old_data and raw_obs.observed_at:
                    import datetime as _dt
                    raw_obs.observed_at = raw_obs.observed_at - _dt.timedelta(hours=2)

                result = self._pipeline.process(raw_obs, now)
                if not result.accepted:
                    logger.debug(
                        "[REJECTED] source=%s reason=%s",
                        raw_obs.source_id, result.rejection_reason,
                    )
                    continue
                if result.warnings:
                    for w in result.warnings:
                        logger.warning("[WARN] source=%s: %s", raw_obs.source_id, w)

                obs = result.observation
                assert obs is not None

                # Journal commit (duplicate-safe)
                try:
                    self._journal.append(obs)
                except Exception as exc:
                    logger.warning("[JOURNAL] Failed to commit: %s", exc)
                    continue

                # Decision engine
                package = self._engine.process(obs, now)
                if package is not None:
                    self.on_package(package)

    # ------------------------------------------------------------------
    @staticmethod
    def _default_on_package(pkg: DecisionPackage) -> None:
        d = pkg.to_display_dict()
        print(
            f"[PKG] track={d['track_id']} "
            f"rec={d['recommendation']} "
            f"verified={d['verified']} "
            f"incident={d['incident_state']} "
            f"| {d['reason'][:80] if d['reason'] else ''}"
        )
