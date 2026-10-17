import asyncio
import copy
import json

import pytest
from conftest import advance, configuration, established, observe, running
from test_ai import wait_idle

from harbor_engine.ai.fake_provider import FakeProvider
from harbor_engine.ai.worker import AIWorker
from harbor_engine.errors import DomainError
from harbor_engine.policy import Policy, load_policy
from harbor_engine.storage import Storage


async def test_repeated_outliers_and_source_heartbeat(demo):
    app, client = demo
    await established(client)
    before = await client.track()
    for _ in range(3):
        await advance(client, 0.5)
        await observe(client, 990, 690)
    a = await client.track()
    assert a["capability"]["data_quality"] == "CONFLICT"
    assert a["last_observed_at"] == before["last_observed_at"]
    assert a["risk"]["current_band"] == "UNKNOWN"
    await advance(client, 5)
    await advance(client, 5)
    session = await client.metadata()
    await client.send(client.event(session["current_time"], "source_heartbeat", {"status": "online"}))
    a = await client.track()
    assert a["capability"]["data_quality"] == "LOST"
    assert a["capability"]["source_health"] == "ONLINE"
    assert app.state.core.state["tracks"]["track_01"]["accepted_count"] == 4


async def test_urgent_observations_reuse_incident(demo):
    _, client = demo
    a = await established(client, 280, 160, 5)
    incident_id = a["incident"]["incident_id"]
    for i in range(3):
        await advance(client)
        await observe(client, 300 + i * 5, 160)
        assert (await client.track())["incident"]["incident_id"] == incident_id


async def test_observation_does_not_advance_manual_clock(demo):
    _, client = demo
    before = await client.metadata()
    body = client.event(
        "2026-10-17T07:00:01Z",
        "observation",
        {"track_id": "t", "coordinate_frame": "harbor_local_m", "x_m": 20, "y_m": 20, "position_sigma_m": 2},
    )
    await client.send(body)
    assert (await client.metadata())["current_time"] == before["current_time"]


async def test_realtime_recovery_marks_stale_and_detects_clock_jump(tmp_path, monkeypatch):
    settings = configuration(tmp_path)
    async with running(settings) as (app, client):
        await client.create("realtime", 42)
        await observe(client, 50)
        saved = app.state.core.state["saved_utc"]
        session_id = client.session_id
    monkeypatch.setattr("harbor_engine.coordinator.utc_now", lambda: saved + 30)
    async with running(settings) as (_, client):
        client.session_id = session_id
        assert (await client.track())["capability"]["data_quality"] == "LOST"
    monkeypatch.setattr("harbor_engine.coordinator.utc_now", lambda: saved - 30)
    async with running(settings) as (_, client):
        client.session_id = session_id
        assert (await client.metadata())["clock_uncertain"]
        assert "CLOCK_UNCERTAIN" in (await client.track())["risk"]["reason_codes"]


async def test_only_one_database_owner(tmp_path):
    first = Storage(str(tmp_path / "same.sqlite3"))
    second = Storage(str(tmp_path / "same.sqlite3"))
    await first.open()
    try:
        with pytest.raises(RuntimeError, match="one server worker"):
            await second.open()
    finally:
        await first.close()
    await second.open()
    await second.close()


async def test_sql_transaction_rollback_is_invisible(tmp_path):
    settings = configuration(tmp_path)
    async with running(settings) as (app, client):
        await client.create("manual", 42)
        await observe(client, 50)
        before = copy.deepcopy(app.state.core.state)
        original = app.state.core.storage.db.execute

        def failing(sql, *args, **kwargs):
            if sql.startswith("INSERT INTO history"):
                raise OSError("Injected mid-transaction failure")
            return original(sql, *args, **kwargs)

        app.state.core.storage.db.execute = failing
        with pytest.raises(DomainError) as error:
            await app.state.core.submit(
                "advance", client.session_id, {"command_id": "rollback", "delta_seconds": 1}
            )
        assert error.value.code == "STORAGE_UNAVAILABLE"
        app.state.core.storage.db.execute = original
        assert app.state.core.state == before
        persisted = await app.state.core.storage.session(client.session_id)
        assert persisted == before
        assert await app.state.core.storage.duplicate("command", client.session_id, "rollback") is None


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("AI_UNAVAILABLE", "UNAVAILABLE"),
        ("AI_TIMEOUT", "TIMED_OUT"),
        ("AI_RATE_LIMIT", "RATE_LIMITED"),
        ("AI_INVALID_RESPONSE", "REJECTED"),
    ],
)
async def test_faults_use_real_validation_path(tmp_path, fault, expected):
    settings = configuration(
        tmp_path, ai_provider="fake", demo_faults_enabled=True, groq_timeout_seconds=0.02
    )
    fake = FakeProvider()
    async with running(settings, fake) as (app, client):
        await client.create("manual", 42)
        await client.request(
            "POST", "/v1/demo/faults", {"command_id": "inject", "fault": fault, "enabled": True}
        )
        await observe(client, 50)
        await client.command("tracks/track_01/enrichment")
        await wait_idle(app.state.core.ai)
        assert app.state.core.ai.status == expected
        assert fake.calls == 0
        assert (await client.track())["recommendation"]["primary_action"] == "VERIFY_PERMISSION"


async def test_late_ai_from_stopped_session_cannot_attach(tmp_path):
    gate = asyncio.Event()
    fake = FakeProvider(gate=gate)
    settings = configuration(tmp_path, ai_provider="fake")
    async with running(settings, fake) as (app, client):
        await client.create("manual", 42)
        await observe(client, 50)
        await client.command("tracks/track_01/enrichment")
        await fake.entered.wait()
        old_session = client.session_id
        old_generation = app.state.core.state["generation"]
        await client.command("stop")
        await client.create("manual", 42)
        with pytest.raises(DomainError):
            await app.state.core.submit("ai_result", old_session, {"generation": old_generation})
        gate.set()
        await wait_idle(app.state.core.ai)
        assert not app.state.core.state["tracks"]


async def test_cooldown_and_circuit_require_future_jobs(tmp_path):
    settings = configuration(tmp_path, ai_provider="fake")
    worker = AIWorker(settings, None, FakeProvider())
    worker.failed("UNAVAILABLE", 30)
    assert worker.status == "UNAVAILABLE"
    worker.failed("UNAVAILABLE", 30)
    worker.failed("UNAVAILABLE", 30)
    assert worker.status == "CIRCUIT_OPEN"
    assert worker.metrics()["cooldown_seconds"] > 59
    assert worker.counts["attempted"] == 0
    worker.failed("MISCONFIGURED", 30)
    assert worker.disabled


def test_invalid_geometry_and_policy_references():
    policy = load_policy("config/demo_policy.yaml").model_dump()
    policy["zones"]["restricted_01"]["vertices"] = [(0, 0), (10, 10), (10, 0), (0, 10)]
    with pytest.raises(ValueError):
        Policy.model_validate(policy)


async def test_openapi_contains_public_assessment_schema(demo):
    _, client = demo
    schema = (await client.http.get("/openapi.json")).json()
    assert "Assessment" in schema["components"]["schemas"]
    assert "additionalProperties" in schema["components"]["schemas"]["Event"]
    assert "engine_operator_token" not in json.dumps(schema)


async def test_second_stop_records_command_identity(demo):
    _, client = demo
    await client.command("stop")
    path = f"/v1/sessions/{client.session_id}/stop"
    body = {"command_id": "second_stop"}
    response = await client.request("POST", path, body)
    assert await client.request("POST", path, body) == response
    result = await client.request(
        "POST",
        "/v1/sessions",
        {
            "command_id": "second_stop",
            "name": "conflict",
            "clock_mode": "manual",
            "start_time": "2026-10-17T07:00:00Z",
            "seed": 42,
        },
        expected=(409,),
    )
    assert result["error"]["code"] == "COMMAND_ID_CONFLICT"


async def test_expired_mission_and_unverified_communication(demo):
    app, client = demo
    await established(client)
    assert "EXPECTED_COMMUNICATION_MISSING" not in (await client.track())["risk"]["reason_codes"]
    await client.bind("research_mission")
    # A deliberately short test policy window; runtime policy changes have no HTTP endpoint.
    app.state.core.policy.missions["research_mission"].end_offset = 3
    await advance(client)
    assert (await client.track())["authorization"]["status"] == "NOT_AUTHORIZED"
