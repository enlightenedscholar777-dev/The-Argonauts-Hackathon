"""Motion inference boundaries, durable sensor ingestion and map georeferencing."""

import copy
import json

import numpy as np
import pytest
from conftest import configuration
from fastapi.testclient import TestClient

from harbor_engine.geography import AREAS, project_area
from harbor_engine.main import create_app
from harbor_engine.motion import POSSIBLE_OBJECTS, classify, features, ingest_detection
from harbor_simulation.integration import DemoController, DemoError, EngineAPI
from harbor_simulation.motion_scenarios import ObjectExercise, trajectory
from harbor_simulation.views import geographic_map, harbor_layout


def test_model_uses_motion_and_withholds_unsupported_claims(monkeypatch):
    for kind in ("directed", "drift", "swimming", "stationary"):
        path = trajectory(kind, 171, count=32, noise=0.2)
        result = classify(path.tolist())
        assert result["status"] == "HYPOTHESIS"
        assert result["behavior"] == kind
        assert result["possible_objects"] == POSSIBLE_OBJECTS[kind]
        assert result["material"] == "Unknown" and not result["calibrated"]
        # Geographic position and absolute time must not leak into classification.
        shifted = path + np.array([1700000000, 700, -1300])
        assert np.allclose(features(path), features(shifted))
        assert classify(path.tolist(), age=5)["status"] == "STALE"
        assert classify(path.tolist(), age=5)["possible_objects"] == []
        assert classify(path.tolist(), sigma=2)["status"] == "UNRESOLVED"
        assert classify(path.tolist(), sigma=2)["possible_objects"] == []
    assert classify(path[:10].tolist())["status"] == "COLLECTING"
    assert classify(path[:10].tolist())["possible_objects"] == []
    unsupported = [[i * 2, i * 100, 0] for i in range(32)]
    assert classify(unsupported)["status"] == "UNRESOLVED"
    duplicate_time = copy.deepcopy(path.tolist())
    duplicate_time[5][0] = duplicate_time[4][0]
    assert classify(duplicate_time)["behavior"] == "unknown"

    def unavailable():
        raise OSError("missing model")

    monkeypatch.setattr("harbor_engine.motion.load_model", unavailable)
    assert classify(path.tolist())["status"] == "UNAVAILABLE"


def test_harbor_object_stream_is_bounded_and_never_sends_labels():
    exercise = ObjectExercise(42, "east_basin", "harbor")
    state = {"now": 0}
    # Exercise ID turnover and stale retirement across the complete 15-minute run.
    for second in range(0, 901, 2):
        rows = exercise.sample(second)
        assert len(rows) == 32 and len({r["area_id"] for r in rows}) == 8
        assert all(set(r) == {"object_id", "area_id", "x_m", "y_m", "position_sigma_m"} for r in rows)
        state["now"] = second
        ingest_detection(state, {"objects": rows}, second)
        assert len(state["detection_histories"]) <= 64
        assert all(len(v["samples"]) <= 32 for v in state["detection_histories"].values())
    local = ObjectExercise(42, "east_basin", "area").sample(0)
    assert len(local) == 4 and {r["area_id"] for r in local} == {"east_basin"}


def test_detection_api_area_maps_persistence_and_sensor_outage(tmp_path):
    settings = configuration(tmp_path, ai_provider="off")
    with TestClient(create_app(settings)) as http:
        api = EngineAPI("http://127.0.0.1", settings, http=http)
        demo = DemoController(api, background=False)
        demo.start(
            "Harbor-wide operations",
            autoplay=False,
            traffic_count=12,
            exercise_area="east_basin",
            detection_scope="area",
        )
        sid = demo.session_id
        path = f"/v1/sessions/{sid}/detections"
        for _ in range(32):
            demo.step()
        snapshot = api.snapshot(sid)
        assert snapshot["session"]["exercise_area"] == "east_basin"
        rows = snapshot["detection"]["objects"]
        assert len(rows) == 4 and all(r["sample_count"] == 17 for r in rows)
        assert any(r["status"] == "HYPOTHESIS" for r in rows)
        body = {
            "command_id": "ordered",
            "observed_at": snapshot["session"]["current_time"],
            "objects": demo.scenario.objects.sample(32),
        }
        with pytest.raises(DemoError, match="FORBIDDEN"):
            api.request("POST", path, body, role="viewer")
        with pytest.raises(DemoError, match="DETECTION_OUT_OF_ORDER"):
            api.request("POST", path, body, role="sensor")
        clock = api.command(f"/v1/sessions/{sid}/clock/advance", delta_seconds=2)
        body["observed_at"] = clock["current_time"]
        body["objects"] = demo.scenario.objects.sample(34)
        result = api.request("POST", path, body, role="sensor")
        assert result == api.request("POST", path, body, role="sensor")
        bad = copy.deepcopy(body)
        bad["command_id"] = "label_leak"
        bad["objects"][0]["kind"] = "garbage"
        with pytest.raises(DemoError, match="INVALID_SCHEMA"):
            api.request("POST", path, bad, role="sensor")
        deck = json.loads(geographic_map(snapshot).to_json())
        layers = {layer["id"]: layer for layer in deck["layers"]}
        track = snapshot["tracks"][0]["estimate"]
        assert layers["engine-tracks"]["data"][0]["position"] == project_area(
            track["x_m"], track["y_m"], "east_basin"
        )
        assert len(layers["detected-objects"]["data"]) == 4
        assert "EAST BASIN" in harbor_layout(snapshot)
        for area in AREAS:
            assert project_area(500, 350, area) == [AREAS[area]["lon"], AREAS[area]["lat"]]
        demo.set_fault("sensor_loss", True)
        for _ in range(6):
            demo.step()
        assert all(
            r["status"] == "STALE" and not r["scores"] for r in api.snapshot(sid)["detection"]["objects"]
        )
        demo.close()
    with TestClient(create_app(settings)) as http:
        api = EngineAPI("http://127.0.0.1", settings, http=http)
        recovered = api.snapshot(sid)
        assert recovered["session"]["exercise_area"] == "east_basin"
        assert recovered["session"]["detection_scope"] == "area"
        assert len(recovered["detection"]["objects"]) == 4
        assert all(r["status"] == "STALE" for r in recovered["detection"]["objects"])
