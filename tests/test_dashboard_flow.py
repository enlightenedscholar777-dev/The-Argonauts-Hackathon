"""Exercise Streamlit widgets against an actual Uvicorn process over loopback HTTP."""

import base64
import json
import os
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import httpx
import pytest
from conftest import configuration

from harbor_simulation.integration import DemoController, EngineAPI

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


@pytest.fixture(params=["off", "fake", "groq"])
def engine_process(tmp_path, monkeypatch, request):
    config = configuration(tmp_path, ai_provider=request.param, groq_api_key="")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    values = {
        "DATABASE_PATH": config.database_path,
        "AI_PROVIDER": request.param,
        "WEB_CONCURRENCY": "1",
        "GROQ_API_KEY": "",
        "AI_MIN_TRACK_INTERVAL_SECONDS": "0",
        "GROQ_MAX_CALLS_PER_MINUTE": "60",
        "GROQ_SOFT_TOKEN_BUDGET_PER_MINUTE": "100000",
        "GROQ_MAX_CALLS_PER_SESSION": "1000",
        "HARBOR_ENGINE_URL": url,
        "DEMO_FAULTS_ENABLED": "true",
        **{
            f"ENGINE_{role.upper()}_TOKEN": getattr(config, f"engine_{role}_token").get_secret_value()
            for role in ("sensor", "operator", "viewer")
        },
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log = (tmp_path / "engine.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "harbor_engine.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=os.environ.copy(),
        stdout=log,
        stderr=log,
        creationflags=flags,
    )
    api = EngineAPI(url, config)
    try:
        with httpx.Client(timeout=1, trust_env=False) as http:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.poll() is None, "Engine failed to start"
                try:
                    if http.get(url + "/health/ready").is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("Engine readiness timed out")
        yield api, process
    finally:
        api.close()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        log.close()


def test_dashboard_start_assessment_acknowledgment_fault_and_stop(engine_process, monkeypatch):
    api, process = engine_process
    controllers = []

    def controlled(api):
        instance = DemoController(api, background=False)
        controllers.append(instance)
        return instance

    monkeypatch.setattr("harbor_simulation.integration.DemoController", controlled)
    streamlit.cache_resource.clear()
    try:
        app = AppTest.from_file("../harbor_simulation/app.py", default_timeout=20).run()
        assert not app.exception
        # Regression: the harbor must appear before any session exists. Maps
        # sent via st.html used to be silently removed by its HTML-only sanitizer.
        assert app.checkbox(key="online_map").value
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        layers = {layer["id"]: layer for layer in deck["layers"]}
        assert len(layers["harbor-terminals"]["data"]) == 11
        assert len(layers["waterway-labels"]["data"]) == 8
        assert len(layers["context-vessels"]["data"]) == 32
        assert layers["exercise-boundary"]["widthUnits"] == "pixels"
        assert layers["exercise-label"]["getTextAnchor"] == "start"
        assert layers["track-labels"]["getTextAnchor"] == "start"
        assert all(layer.get("widthUnits", "pixels") == "pixels" for layer in deck["layers"])
        assert not layers["engine-tracks"]["data"]
        assert len(app.image) == 2
        app.checkbox(key="online_map").uncheck().run()
        assert not app.exception
        assert len(app.image) == 2
        for element in app.image:
            assert element.value[0].startswith("data:image/svg+xml;base64,")
            svg = base64.b64decode(element.value[0].split(",", 1)[1]).decode()
            assert ET.fromstring(svg).tag.endswith("svg")
        assert "Pier T" in base64.b64decode(app.image[0].value[0].split(",", 1)[1]).decode()
        app.checkbox(key="autoplay").uncheck().run()
        app.button(key="start").click().run()
        assert not app.exception
        assert not app.error
        sid = api.status()["active_session_id"]
        assert sid
        assert len(api.snapshot(sid)["tracks"]) == 2
        assert "unknown_01" in base64.b64decode(app.image[1].value[0].split(",", 1)[1]).decode()
        app.checkbox(key="online_map").check().run()
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        layers = {layer["id"]: layer for layer in deck["layers"]}
        assert len(layers["engine-tracks"]["data"]) == 2
        assert len(layers["engine-routes"]["data"]) == 2
        from harbor_simulation.views import project

        # The display must use the session's routes, with the same local-to-map
        # transform as its tracks, rather than independently invented lines.
        assert [line["path"] for line in layers["engine-routes"]["data"]] == [
            [project(*point) for point in vertices] for vertices in api.snapshot(sid)["routes"].values()
        ]
        app.selectbox(key="map_focus").select("Exercise area").run()
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        assert deck["initialViewState"]["zoom"] == 15
        app.checkbox(key="map_context").uncheck().run()
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        layers = {layer["id"]: layer for layer in deck["layers"]}
        assert layers["context-vessels"]["visible"] is False
        assert len(layers["engine-tracks"]["data"]) == 2
        app.selectbox(key="map_focus").select("Pier T").run()
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        assert deck["initialViewState"]["zoom"] == 14.5
        app.selectbox(key="map_focus").select("Exercise area").run()
        app.button(key="step").click().run()
        demo = controllers[0]
        assert demo.view()["elapsed"] == 1
        app.select_slider(key="playback_speed").set_value(4).run()
        assert demo.period == 0.25
        app.run()
        assert demo.period == 0.25
        assert demo.view()["elapsed"] == 1
        for _ in range(39):
            demo.step()
        app.run()
        assert not app.exception
        assert any("unknown_01 · HIGH" in element.value for element in app.subheader)
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        assert next(layer for layer in deck["layers"] if layer["id"] == "engine-forecasts")["data"]
        mode = api.settings.ai_provider
        expected_ai = (
            "off / OFF" if mode == "off" else "groq / MISCONFIGURED" if mode == "groq" else "fake / MOCK"
        )
        assert any(
            element.label == "AI provider / status" and element.value == expected_ai for element in app.metric
        )
        if mode == "fake":
            app.button(key="ai_fault").click().run()
            assert not app.exception
            assert any(
                element.label == "AI provider / status" and element.value == "fake / UNAVAILABLE"
                for element in app.metric
            )
            assert any(
                element.label == "CPU decision core" and element.value == "READY" for element in app.metric
            )
        app.button(key="ack_unknown_01").click().run()
        assert not app.exception
        track = next(t for t in api.snapshot(sid)["tracks"] if t["track_id"] == "unknown_01")
        assert track["incident"]["state"] == "HUMAN_OWNED"
        app.button(key="history").click().run()
        history = app.session_state["audit_history"]
        assert history[0] == sid and history[1]["items"]
        app.run()
        assert app.session_state["audit_history"] == history
        app.button(key="replay_fault").click().run()
        app.button(key="step").click().run()
        assert demo.view()["counts"]["DUPLICATE"] == 2
        app.button(key="sensor_fault").click().run()
        for _ in range(12):
            demo.step()
        app.run()
        assert not app.exception
        assert any(element.label == "Position evidence" and element.value == "LOST" for element in app.metric)
        app.button(key="stop").click().run()
        assert api.status()["active_session_id"] is None
        assert not app.exception
        app.button(key="preset_Busy harbor").click().run()
        assert app.selectbox(key="scenario").value == "Busy harbor"
        busy_id = api.status()["active_session_id"]
        assert len(api.snapshot(busy_id)["tracks"]) == 8
        assert len(demo.view()["context"]["traffic"]) == 32
        app.button(key="preset_Normal operations").click().run()
        assert api.snapshot(busy_id)["session"]["stopped"]
        assert len(api.snapshot(api.status()["active_session_id"])["tracks"]) == 1
        app.button(key="stop").click().run()
        # The UI must clear current results when the engine goes away.
        process.terminate()
        process.wait(timeout=10)
        app.run()
        assert not app.exception
        assert app.error
        assert not app.metric
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        layers = {layer["id"]: layer for layer in deck["layers"]}
        assert len(layers["harbor-terminals"]["data"]) == 11
        assert not layers["engine-tracks"]["data"]
        for element in app.image:
            assert "unknown_01" not in base64.b64decode(element.value[0].split(",", 1)[1]).decode()
    finally:
        for demo in controllers:
            demo.close()
        streamlit.cache_resource.clear()
