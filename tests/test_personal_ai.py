import json

import pytest
from conftest import configuration
from fastapi.testclient import TestClient

from harbor_engine.ai.fake_provider import FakeProvider
from harbor_engine.main import create_app
from harbor_simulation.integration import DemoController, DemoError, EngineAPI
from harbor_simulation.personal_ai import PersonalAI
from scripts.launch_space import space_environment
from scripts.prepare_space import prepare


def test_personal_key_and_explanation_do_not_enter_shared_state(tmp_path):
    config = configuration(tmp_path)
    with TestClient(create_app(config)) as http:
        api = EngineAPI("http://127.0.0.1", config, http=http)
        demo = DemoController(api, background=False)
        demo.start("Harbor approach", autoplay=False)
        sid, tid = demo.session_id, "unknown_01"
        first, second = PersonalAI("visitor_one_secret_value"), PersonalAI("visitor_two_secret_value")
        fake = FakeProvider()
        captured = []

        def factory(settings):
            captured.append(settings.groq_api_key.get_secret_value())
            return fake

        assert fake.calls == 0
        first.request(api, sid, tid, factory)
        assert fake.calls == 1 and first.results and not first.error
        assert captured == ["visitor_one_secret_value"]
        assert not second.results and not second.calls
        assert config.groq_api_key.get_secret_value() == ""
        snapshot = api.snapshot(sid)
        assert all(t["ai_enrichment"] is None for t in snapshot["tracks"])
        assert api.status()["ai"]["counters"]["attempted"] == 0
        first.request(api, sid, tid, factory)
        assert fake.calls == 1  # repeated clicks respect the private cooldown
        with pytest.raises(DemoError, match="FORBIDDEN"):
            api.request("GET", f"/v1/sessions/{sid}/tracks/{tid}/explanation-context", role="viewer")
        demo.close()
    for path in tmp_path.glob("*.sqlite3*"):
        assert b"visitor_one_secret_value" not in path.read_bytes()
        assert b"visitor_two_secret_value" not in path.read_bytes()


@pytest.mark.parametrize("mode", ["rate_limit", "credentials", "malformed", "unknown_evidence"])
def test_personal_failures_are_private_and_never_retried(tmp_path, mode):
    config = configuration(tmp_path)
    with TestClient(create_app(config)) as http:
        api = EngineAPI("http://127.0.0.1", config, http=http)
        demo = DemoController(api, background=False)
        demo.start("Harbor approach", autoplay=False)
        person = PersonalAI("secret_never_shown_in_errors")
        fake = FakeProvider(mode)
        person.request(api, demo.session_id, "unknown_01", lambda _: fake)
        assert fake.calls == 1 and person.error and not person.results
        assert "secret_never" not in person.error
        person.request(api, demo.session_id, "unknown_01", lambda _: fake)
        assert fake.calls == 1
        assert api.status()["core"] == "READY"
        demo.close()


def test_space_environment_disables_owner_key_and_uses_unique_tokens():
    environment = space_environment({"GROQ_API_KEY": "owner_secret", "AI_PROVIDER": "groq"})
    assert environment["GROQ_API_KEY"] == "" and environment["AI_PROVIDER"] == "off"
    tokens = [environment[f"ENGINE_{role}_TOKEN"] for role in ("SENSOR", "OPERATOR", "VIEWER")]
    assert len(set(tokens)) == 3 and all(len(t) >= 24 for t in tokens)
    assert "owner_secret" not in json.dumps(environment)


def test_space_export_is_allowlisted_and_never_overwrites(tmp_path):
    destination = tmp_path / "space"
    assert prepare(destination) > 20
    assert (destination / "src/harbor_engine/models/motion_forest.json").exists()
    assert (destination / "Dockerfile").exists()
    assert not (destination / ".env").exists()
    assert not (destination / "runtime").exists()
    assert not (destination / ".git").exists()
    assert not list(destination.rglob("*.sqlite3"))
    with pytest.raises(ValueError):
        prepare(destination)
