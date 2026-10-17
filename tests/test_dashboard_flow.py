"""Exercise Streamlit widgets against an actual Uvicorn process over loopback HTTP."""

import os
import socket
import subprocess
import sys
import time

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
        app.checkbox(key="autoplay").uncheck().run()
        app.button(key="start").click().run()
        assert not app.exception
        assert not app.error
        sid = api.status()["active_session_id"]
        assert sid
        assert len(api.snapshot(sid)["tracks"]) == 2
        app.button(key="step").click().run()
        demo = controllers[0]
        assert demo.view()["elapsed"] == 1
        for _ in range(39):
            demo.step()
        app.run()
        assert not app.exception
        assert any("unknown_01 · HIGH" in element.value for element in app.subheader)
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
        # The UI must clear current results when the engine goes away.
        process.terminate()
        process.wait(timeout=10)
        app.run()
        assert not app.exception
        assert app.error
        assert not app.metric
    finally:
        for demo in controllers:
            demo.close()
        streamlit.cache_resource.clear()
