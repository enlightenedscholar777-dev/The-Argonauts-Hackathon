"""Verify the merged sensor bridge against the real API and persistent decision core."""

import time

import pytest
from conftest import configuration
from fastapi.testclient import TestClient

from harbor_engine.main import create_app
from harbor_simulation.integration import DemoController, DemoError, EngineAPI, position_payload
from harbor_simulation.views import local_map
from simulator.data_models.observation import BearingRange, Observation


@pytest.fixture
def integrated(tmp_path):
    settings = configuration(tmp_path, ai_provider="off")
    with TestClient(create_app(settings)) as http:
        demo = DemoController(EngineAPI("http://127.0.0.1", settings, http=http), background=False)
        yield demo
        demo.close()


def by_track(demo):
    return {t["track_id"]: t for t in demo.api.snapshot(demo.session_id)["tracks"]}


def test_range_bearing_projection_and_measurement_limits():
    observation = Observation(track_id="unknown", value=BearingRange(90, 20, 10, 30, 2, 3))
    payload = position_payload(observation)
    assert payload["x_m"] == pytest.approx(30)
    assert payload["y_m"] == pytest.approx(30)
    assert payload["position_sigma_m"] > 3
    assert payload["claimed_vehicle_id"] is None
    observation.value.range_m = None
    with pytest.raises(DemoError, match="range"):
        position_payload(observation)


def test_pako_to_engine_handoff_replay_loss_and_recovery(integrated):
    demo = integrated
    demo.start(autoplay=False)
    with pytest.raises(DemoError, match="already active"):
        demo.start()
    for _ in range(40):
        demo.step()
    tracks = by_track(demo)
    unknown, research = tracks["unknown_01"], tracks["research_auv_02"]
    assert unknown["authorization"]["status"] == "UNKNOWN"
    assert unknown["risk"]["current_band"] == "HIGH"
    assert unknown["incident"]["handoff_required"]
    assert research["risk"]["current_band"] == "LOW"
    assert research["authorization"]["status"] == "AUTHORIZED"
    demo.acknowledge(demo.session_id, "unknown_01")
    assert by_track(demo)["unknown_01"]["incident"]["state"] == "HUMAN_OWNED"
    demo.set_fault("replay", True)
    demo.step()
    assert demo.view()["counts"]["DUPLICATE"] == 2
    demo.set_fault("sensor_loss", True)
    for _ in range(12):
        demo.step()
    tracks = by_track(demo)
    assert all(t["capability"]["data_quality"] == "LOST" for t in tracks.values())
    assert tracks["research_auv_02"]["source"]["observation_age_seconds"] == 12
    assert demo.api.snapshot(demo.session_id)["sources"]["sim_telemetry_01"]["health"] == "ONLINE"
    demo.set_fault("sensor_loss", False)
    for _ in range(3):
        demo.step()
    assert by_track(demo)["research_auv_02"]["capability"]["data_quality"] == "FRESH"
    snapshot = demo.api.snapshot(demo.session_id)
    assert "unknown_01" in local_map(snapshot)
    assert "http" not in local_map(snapshot).replace("http://www.w3.org/2000/svg", "")
    demo.stop(demo.session_id)
    assert demo.api.status()["active_session_id"] is None


def test_confirmed_research_deviation(integrated):
    integrated.start("Research route deviation", autoplay=False)
    for _ in range(33):
        integrated.step()
    track = by_track(integrated)["research_auv_02"]
    assert "ROUTE_DEVIATION" in track["risk"]["reason_codes"]
    assert track["authorization"]["status"] == "AUTHORIZED"
    assert track["recommendation"]["primary_action"] != "MONITOR"


@pytest.mark.parametrize("mode", ["fake", "groq"])
def test_optional_ai_failure_does_not_stop_integration(tmp_path, mode):
    settings = configuration(
        tmp_path,
        ai_provider=mode,
        groq_api_key="",
        demo_faults_enabled=True,
        ai_min_track_interval_seconds=0,
        groq_max_calls_per_minute=60,
        groq_soft_token_budget_per_minute=100000,
    )
    with TestClient(create_app(settings)) as http:
        demo = DemoController(EngineAPI("http://127.0.0.1", settings, http=http), background=False)
        demo.start("Normal operations", autoplay=False)
        if mode == "fake":
            demo.ai_fault(True)
        for _ in range(8):
            demo.step()
        track = by_track(demo)["research_auv_02"]
        assert track["risk"]["current_band"] == "LOW"
        assert demo.api.status()["core"] == "READY"
        if mode == "groq":
            assert demo.api.status()["ai"]["status"] == "MISCONFIGURED"
        else:
            assert "AI_UNAVAILABLE" in demo.api.snapshot(demo.session_id)["simulated_faults"]
            deadline = time.monotonic() + 2
            while demo.api.status()["ai"]["status"] == "PENDING" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert demo.api.status()["ai"]["status"] == "UNAVAILABLE"
        demo.close()


def test_background_feeder_pause_and_viewers_do_not_advance_clock(tmp_path):
    settings = configuration(tmp_path, ai_provider="off")
    with TestClient(create_app(settings)) as http:
        demo = DemoController(EngineAPI("http://127.0.0.1", settings, http=http), period=0.04)
        try:
            demo.start("Normal operations")
            deadline = time.monotonic() + 5
            while demo.view()["elapsed"] < 3 and time.monotonic() < deadline:
                time.sleep(0.02)
            demo.pause()
            before = demo.api.snapshot(demo.session_id)["session"]["current_time"]
            for _ in range(5):
                demo.view()
                demo.api.snapshot(demo.session_id)
            time.sleep(0.1)
            assert demo.view()["elapsed"] >= 3
            assert demo.api.snapshot(demo.session_id)["session"]["current_time"] == before
        finally:
            demo.close()
