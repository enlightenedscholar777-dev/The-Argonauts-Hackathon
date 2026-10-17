"""
Smoke tests — verify that the happy path and basic fault paths run without errors.
"""

from __future__ import annotations

from datetime import datetime, timezone


def test_ingestion_pipeline_accepts_valid_observation():
    from simulator.data_models.observation import (
        MeasurementType, Observation, Position, SensorType, ValueOrigin,
    )
    from simulator.ingestion.pipeline import IngestionPipeline

    obs = Observation(
        source_id="sonar-01",
        sensor_type=SensorType.SONAR,
        value_origin=ValueOrigin.MEASURED,
        measurement_type=MeasurementType.POSITION_3D,
        value=Position(x=10.0, y=20.0, depth=-5.0, sigma_x=2.0, sigma_y=2.0),
        observed_at=datetime.now(timezone.utc),
        track_id="T-001",
    )
    result = IngestionPipeline().process(obs)
    assert result.accepted, f"Expected accepted: {result.rejection_reason}"


def test_ingestion_pipeline_rejects_future_timestamp():
    from datetime import timedelta
    from simulator.data_models.observation import (
        MeasurementType, Observation, Position, SensorType, ValueOrigin,
    )
    from simulator.ingestion.pipeline import IngestionPipeline

    future = datetime.now(timezone.utc) + timedelta(seconds=300)
    obs = Observation(
        source_id="sonar-01",
        sensor_type=SensorType.SONAR,
        value_origin=ValueOrigin.MEASURED,
        measurement_type=MeasurementType.POSITION_3D,
        value=Position(x=10.0, y=20.0, depth=-5.0),
        observed_at=future,
        track_id="T-001",
    )
    result = IngestionPipeline().process(obs)
    assert not result.accepted


def test_kalman_tracker_initialises_and_updates():
    from simulator.data_models.observation import (
        MeasurementType, Observation, Position, SensorType, ValueOrigin,
    )
    from simulator.engine.tracker.kalman_tracker import KalmanTracker

    tracker = KalmanTracker()
    for i in range(5):
        obs = Observation(
            source_id="telem-01",
            sensor_type=SensorType.AUV_TELEM,
            value_origin=ValueOrigin.REPORTED,
            measurement_type=MeasurementType.POSITION_3D,
            value=Position(x=float(i), y=float(i), depth=-5.0, sigma_x=3.0, sigma_y=3.0),
            observed_at=datetime(2025, 1, 1, 8, 0, i * 5, tzinfo=timezone.utc),
            track_id="AUV-01",
            vehicle_id="AUV-01",
        )
        state = tracker.update(obs)
    assert state is not None
    assert state.track_id == "AUV-01"
    assert state.vehicle_id == "AUV-01"


def test_policy_engine_flags_unknown_identity():
    from simulator.engine.tracker.kalman_tracker import TrackState
    from simulator.engine.policy.policy_engine import AuthorizationVerdict, PolicyEngine
    import numpy as np

    track = TrackState(track_id="T-001", x=np.zeros(6), P=np.eye(6))
    result = PolicyEngine().evaluate(track, missions=[], zones=[], now=datetime.now(timezone.utc))
    assert result.verdict == AuthorizationVerdict.UNKNOWN
    assert any(f.code == "UNKNOWN_IDENTITY" for f in result.findings)


def test_incident_fsm_happy_path():
    from simulator.engine.incident.incident_fsm import (
        IncidentEvent, IncidentManager, IncidentState,
    )
    mgr = IncidentManager()
    mgr.advance("T-001", IncidentEvent.CONCERN_RAISED)
    mgr.advance("T-001", IncidentEvent.HANDOFF_REQUESTED)
    mgr.advance("T-001", IncidentEvent.HUMAN_ACKNOWLEDGED)
    incident = mgr.get_or_create("T-001")
    assert incident.state == IncidentState.HUMAN_OWNED


def test_demo_scenario_runs_without_error():
    """End-to-end smoke test: run the demo scenario for 10 ticks."""
    from simulator.orchestrator.runner import ScenarioConfig, SimulatorRunner

    packages = []
    scenario = ScenarioConfig.demo()
    runner   = SimulatorRunner(scenario, on_package=packages.append)
    runner.run(steps=10)
    # At least one package should have been emitted
    assert len(packages) > 0


def test_fault_drop_sensor():
    """Dropped sensor should produce no packages for that source."""
    from simulator.orchestrator.runner import ScenarioConfig, SimulatorRunner

    packages = []
    scenario = ScenarioConfig.demo()
    runner   = SimulatorRunner(scenario, on_package=packages.append)
    runner.faults.drop_sensor("sonar-01")
    runner.faults.drop_sensor("telem-01")
    runner.faults.drop_sensor("ais-01")
    runner.faults.drop_sensor("env-01")
    runner.faults.drop_sensor("notes-01")
    runner.run(steps=10)
    # All sensors dropped → no packages
    assert len(packages) == 0
