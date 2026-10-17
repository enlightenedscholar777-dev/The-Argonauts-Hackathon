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
from streamlit.proto.TextInput_pb2 import TextInput  # noqa: E402


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
        "HARBOR_AUTOSTART": "false",
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

        def navigate(page):
            app.radio(key="navigation").set_value(page).run()
            assert not app.exception

        def layers():
            deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
            return {layer["id"]: layer for layer in deck["layers"]}

        assert not app.exception
        assert app.checkbox(key="online_map").value
        initial = layers()
        assert len(initial["harbor-terminals"]["data"]) == 11
        assert len(initial["waterway-labels"]["data"]) == 8
        # One of the 32 preview voyages waits off-map for channel admission.
        assert len(initial["context-vessels"]["data"]) == 31
        assert initial["exercise-boundary"]["widthUnits"] == "pixels"
        assert initial["exercise-label"]["getTextAnchor"] == "start"
        assert initial["track-labels"]["getTextAnchor"] == "start"
        assert all(layer.get("widthUnits", "pixels") == "pixels" for layer in initial.values())
        assert not initial["engine-tracks"]["data"]
        assert len(app.image) == 2
        app.checkbox(key="online_map").uncheck().run()
        for element in app.image:
            svg = base64.b64decode(element.value[0].split(",", 1)[1]).decode()
            assert ET.fromstring(svg).tag.endswith("svg")
        assert "Pier T" in base64.b64decode(app.image[0].value[0].split(",", 1)[1]).decode()
        navigate("Simulation")
        app.checkbox(key="autoplay").uncheck().run()
        app.button(key="start").click().run()
        assert not app.exception
        assert not app.error
        sid = api.status()["active_session_id"]
        assert len(api.snapshot(sid)["tracks"]) == 2
        app.checkbox(key="online_map").check().run()
        active_layers = layers()
        assert len(active_layers["engine-tracks"]["data"]) == 2
        from harbor_simulation.views import project

        assert [line["path"] for line in active_layers["engine-routes"]["data"]] == [
            [project(*point) for point in vertices] for vertices in api.snapshot(sid)["routes"].values()
        ]
        app.selectbox(key="map_focus").select("Exercise area").run()
        assert json.loads(app.get("deck_gl_json_chart")[0].proto.json)["initialViewState"]["zoom"] == 15
        app.checkbox(key="map_context").uncheck().run()
        assert layers()["context-vessels"]["visible"] is False
        assert len(layers()["engine-tracks"]["data"]) == 2
        app.selectbox(key="map_focus").select("Pier T").run()
        assert json.loads(app.get("deck_gl_json_chart")[0].proto.json)["initialViewState"]["zoom"] == 14.5
        app.button(key="step").click().run()
        demo = controllers[0]
        assert demo.view()["elapsed"] == 1
        app.select_slider(key="playback_speed").set_value(4).run()
        app.run()
        assert demo.period == 0.25
        assert demo.view()["elapsed"] == 1
        for _ in range(39):
            demo.step()
        navigate("Overview")
        assert layers()["engine-forecasts"]["data"]
        assert any("Review this contact now" in element.value for element in app.markdown)
        app.button(key="review_priority").click().run()
        assert not app.exception
        assert app.radio(key="navigation").value == "Contacts"
        assert app.selectbox(key="selected_contact").value == "unknown_01"
        assert "Selected: unknown_01" in base64.b64decode(app.image[0].value[0].split(",", 1)[1]).decode()
        app.button(key="ack_unknown_01").click().run()
        assert not app.exception
        track = next(t for t in api.snapshot(sid)["tracks"] if t["track_id"] == "unknown_01")
        assert track["incident"]["state"] == "HUMAN_OWNED"
        assert any("Review acknowledged" in s.value for s in app.success)
        app.text_input(key="contact_search").set_value("no matching contact").run()
        assert any("No contacts match" in s.value for s in app.info)
        app.text_input(key="contact_search").set_value("").run()
        app.radio(key="contact_filter").set_value("Acknowledged reviews").run()
        assert app.selectbox(key="selected_contact").value == "unknown_01"
        navigate("Traffic")
        surface = api.snapshot(sid)["surface"]
        assert any(
            e.label == "Observed surface vessels" and e.value == str(surface["observations"])
            for e in app.metric
        )
        alerts = [v for v in surface["vessels"] if v["reason_codes"]]
        assert alerts
        app.selectbox(key="surface_selection").select(alerts[0]["vessel_id"]).run()
        app.button(key="surface_ack").click().run()
        assert not app.exception
        assert any("Traffic review acknowledged" in e.value for e in app.success)
        navigate("Detection")
        assert app.radio(key="navigation").options[-2:] == ["Activity", "Detection"]
        assert any(e.label == "Objects observed" and e.value == "32" for e in app.metric)
        assert len(layers()["detected-objects"]["data"]) == 32
        assert any("Material" in str(table.value) for table in app.dataframe)
        detection_table = next(table.value for table in app.dataframe if "Possible objects (unconfirmed)" in table.value.columns)
        assert "Needs confirmation" in set(detection_table["Evidence"])
        assert detection_table["Possible objects (unconfirmed)"].str.contains("debris|animal|craft|object", case=False).any()
        app.selectbox(key="detection_area_filter").select("East Basin").run()
        assert len(app.selectbox(key="detection_object").options) == 4
        assert not app.exception
        navigate("Activity")
        mode = api.settings.ai_provider
        expected_ai = (
            "off / OFF" if mode == "off" else "groq / MISCONFIGURED" if mode == "groq" else "fake / MOCK"
        )
        assert any(e.label == "AI provider / status" and e.value == expected_ai for e in app.metric)
        if mode == "off":
            from harbor_engine.ai.fake_provider import FakeProvider
            from harbor_engine.ai.worker import validate_result
            from harbor_simulation.personal_ai import PersonalAI

            personal_calls = []

            async def private_completion(self, settings, snapshot, factory):
                personal_calls.append(settings.groq_api_key.get_secret_value())
                result = await FakeProvider().complete(snapshot)
                return validate_result(result.content, snapshot)

            monkeypatch.setattr(PersonalAI, "_complete", private_completion)
            app.text_input(key="groq_key_input").set_value("gsk_visitor_key_for_ui_test_only")
            next(button for button in app.button if button.label == "Use my key").click().run()
            assert not app.exception and not personal_calls
            assert app.text_input(key="groq_key_input").proto.type == TextInput.PASSWORD
            navigate("Contacts")
            app.button(key="personal_enrich_unknown_01").click().run()
            assert not app.exception
            assert len(personal_calls) == 1
            assert app.session_state["personal_ai"].results
            app.run()
            assert len(personal_calls) == 1
            another_browser = AppTest.from_file("../harbor_simulation/app.py", default_timeout=20).run()
            assert "personal_ai" not in another_browser.session_state
            assert not another_browser.exception
            app.button(key="remove_groq_key").click().run()
            assert "personal_ai" not in app.session_state
            navigate("Activity")
        app.button(key="history").click().run()
        history = app.session_state["audit_history"]
        assert history[0] == sid and history[1]["items"]
        app.run()
        assert app.session_state["audit_history"] == history
        navigate("Simulation")
        if mode == "fake":
            app.button(key="ai_fault").click().run()
            navigate("Contacts")
            app.radio(key="contact_filter").set_value("All contacts").run()
            app.selectbox(key="selected_contact").select("unknown_01").run()
            app.button(key="enrich_unknown_01").click().run()
            navigate("Activity")
            assert any(
                e.label == "AI provider / status" and e.value == "fake / UNAVAILABLE" for e in app.metric
            )
            assert any(e.label == "CPU decision core" and e.value == "READY" for e in app.metric)
            navigate("Simulation")
        app.button(key="replay_fault").click().run()
        app.button(key="step").click().run()
        assert demo.view()["counts"]["DUPLICATE"] == 2
        app.button(key="sensor_fault").click().run()
        for _ in range(12):
            demo.step()
        navigate("Contacts")
        app.selectbox(key="selected_contact").select("unknown_01").run()
        assert any(e.label == "Position evidence" and e.value == "Position updates lost" for e in app.metric)
        navigate("Overview")
        assert any("lost or conflicting" in e.value for e in app.warning)
        navigate("Simulation")
        app.button(key="stop").click().run()
        assert api.status()["active_session_id"] is None
        assert not app.exception
        app.button(key="preset_Busy harbor").click().run()
        assert app.selectbox(key="scenario").value == "Busy harbor"
        busy_id = api.status()["active_session_id"]
        assert len(api.snapshot(busy_id)["tracks"]) == 8
        assert len(demo.view()["context"]["traffic"]) == 48
        app.button(key="preset_Normal operations").click().run()
        assert api.snapshot(busy_id)["session"]["stopped"]
        assert len(api.snapshot(api.status()["active_session_id"])["tracks"]) == 1
        app.button(key="stop").click().run()
        navigate("Overview")
        assert any("final recorded assessments" in e.value for e in app.warning)
        process.terminate()
        process.wait(timeout=10)
        app.run()
        assert not app.exception
        assert app.error
        assert not app.metric
        assert not layers()["engine-tracks"]["data"]
        for element in app.image:
            assert "unknown_01" not in base64.b64decode(element.value[0].split(",", 1)[1]).decode()
    finally:
        for demo in controllers:
            demo.close()
        streamlit.cache_resource.clear()
