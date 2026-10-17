"""Traffic geometry, analytical warning behavior, persistence and API boundaries."""

import copy
import math

import pytest
from conftest import configuration
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from harbor_engine.main import create_app
from harbor_engine.surface import assess_surface
from harbor_simulation.integration import DemoController, DemoError, EngineAPI
from harbor_simulation.map_catalog import TERMINALS
from harbor_simulation.traffic import HarborTraffic
from harbor_simulation.voyages import VOYAGE_ROUTES, metres


def vessel(identifier, east, vx=0):
    return dict(
        vessel_id=identifier,
        lon=-118.22 + east / 92500,
        lat=33.75,
        vx_mps=vx,
        vy_mps=0,
        route_id="route_1",
        destination="Pier T",
        route=[[-118.24, 33.75], [-118.20, 33.75]],
        status="UNDERWAY",
        phase="INBOUND",
        scheduled_arrival_s=600,
        eta_s=600,
        delay_s=0,
    )


def test_traffic_models_warn_before_encounter_and_degrade_with_age():
    ships = [vessel("a", 0, 4), vessel("b", 400, -4)]
    report = assess_surface(ships)
    assert report["alerts"] == 2
    assert report["vessels"][0]["encounters"] == [
        {"vessel_id": "b", "closest_in_s": 50.0, "separation_m": 0.0}
    ]
    assert report["vessels"][0]["concern"] == "HIGH"
    assert all(
        v["reason_codes"] == ["POSITION_LOST"] and not v["encounters"]
        for v in assess_surface(ships, 11)["vessels"]
    )
    ships[1]["vx_mps"] = 4
    assert assess_surface(ships)["alerts"] == 0
    ships[0]["lat"] += 0.003
    ships[1]["delay_s"] = 40
    report = assess_surface(ships)
    assert "OFF_PLANNED_ROUTE" in report["vessels"][0]["reason_codes"]
    assert report["vessels"][1]["recommendation"].startswith("Review the berth queue")


def test_routes_avoid_schematic_land_and_dense_voyages_do_not_overlap():
    land = [Polygon(t["outline"]) for t in TERMINALS]
    for plan in VOYAGE_ROUTES:
        assert all(not LineString(plan["atlas"]).intersects(p) for p in land), plan["route_id"]
    traffic = HarborTraffic(seed=42, count=100)
    saw_berth = saw_departure = False
    for second in range(0, 901, 15):
        rows = traffic.sample(second)
        assert len({r["vessel_id"] for r in rows}) == 100
        visible = [r for r in rows if r["lon"] is not None]
        for i, row in enumerate(visible):
            assert all(not p.covers(Point(row["anchor"])) for p in land)
            assert row["speed_mps"] < 25
            for other in visible[i + 1 :]:
                assert metres([row["lon"], row["lat"]], [other["lon"], other["lat"]]) >= 120 - 1e-7
                assert math.dist(row["anchor"], other["anchor"]) >= 18 - 1e-7
        saw_berth |= any(r["phase"] == "BERTHED" for r in rows)
        saw_departure |= any(r["phase"] == "DEPARTED" for r in rows)
    assert saw_berth and saw_departure
    assert traffic.sample(15) == HarborTraffic(seed=42, count=100).sample(15)


def test_surface_batch_is_durable_idempotent_authorized_and_revision_checked(tmp_path):
    settings = configuration(tmp_path, ai_provider="off")
    with TestClient(create_app(settings)) as http:
        api = EngineAPI("http://127.0.0.1", settings, http=http)
        session = api.command(
            "/v1/sessions",
            name="surface-test",
            clock_mode="manual",
            start_time="2026-01-01T00:00:00Z",
            seed=42,
        )
        sid = session["session_id"]
        path = f"/v1/sessions/{sid}/surface"
        body = dict(
            command_id="batch_1",
            observed_at=session["current_time"],
            vessels=[vessel("a", 0, 4), vessel("b", 400, -4)],
        )
        with pytest.raises(DemoError, match="FORBIDDEN"):
            api.request("POST", path, body, role="viewer")
        result = api.request("POST", path, body, role="sensor")
        assert api.request("POST", path, body, role="sensor") == result
        assert len(api.snapshot(sid)["surface"]["vessels"]) == 2
        with pytest.raises(DemoError, match="STALE_REVISION"):
            api.command(path + "/a/ack", expected_revision=999)
        api.command(path + "/a/ack", expected_revision=result["revision"])
        assert api.snapshot(sid)["surface"]["vessels"][0]["acknowledgment"]
        bad = copy.deepcopy(body)
        bad.update(command_id="bad_time", observed_at="2026-01-01T00:00:50Z")
        with pytest.raises(DemoError, match="SURFACE_TIMESTAMP"):
            api.request("POST", path, bad)
        for _ in range(3):
            api.command(f"/v1/sessions/{sid}/clock/advance", delta_seconds=4)
        assert api.snapshot(sid)["surface"]["vessels"][0]["reason_codes"] == ["POSITION_LOST"]
        assert api.snapshot(sid)["surface"]["vessels"][0]["acknowledgment"] is None
    with TestClient(create_app(settings)) as http:
        api = EngineAPI("http://127.0.0.1", settings, http=http)
        assert api.snapshot(sid)["surface"]["observations"] == 2
        history = api.request("GET", f"/v1/sessions/{sid}/history?limit=100", role="viewer")
        assert any(item["kind"] == "surface_ack" for item in history["items"])


def test_harbor_wide_surface_positions_are_engine_assessed(tmp_path):
    settings = configuration(tmp_path, ai_provider="off")
    with TestClient(create_app(settings)) as http:
        demo = DemoController(EngineAPI("http://127.0.0.1", settings, http=http), background=False)
        demo.start("Harbor-wide operations", autoplay=False, traffic_count=48)
        for _ in range(5):
            demo.step()
        state = demo.view()
        snapshot = demo.api.snapshot(demo.session_id)
        positioned = [v for v in state["context"]["traffic"] if v["lon"] is not None]
        assert snapshot["surface"]["observations"] == len(positioned)
        assert {v["vessel_id"] for v in snapshot["surface"]["vessels"]} == {
            v["vessel_id"] for v in positioned
        }
        assert len(snapshot["tracks"]) == 8
        assert state["duration"] == 900
        assert state["counts"]["SURFACE_OBSERVATIONS"] >= 200
        demo.pause()
        before = demo.view()["context"]
        demo.view()
        assert demo.view()["context"] == before
        demo.close()
