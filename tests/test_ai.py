import asyncio

import pytest
from conftest import advance, configuration, established, observe, running

from harbor_engine.ai.fake_provider import FakeProvider
from harbor_engine.ai.worker import make_snapshot, validate_result


async def wait_idle(worker):
    # Cooperative scheduling only; a deadline detects deadlocks without arbitrary sleeps.
    async with asyncio.timeout(3):
        while worker.pending or worker.inflight:
            await asyncio.sleep(0)


@pytest.mark.parametrize(
    "mode,status",
    [
        ("success", "MOCK"),
        ("rate_limit", "RATE_LIMITED"),
        ("timeout", "TIMED_OUT"),
        ("unavailable", "UNAVAILABLE"),
        ("server_error", "UNAVAILABLE"),
        ("credentials", "MISCONFIGURED"),
        ("missing_model", "MISCONFIGURED"),
        ("refusal", "REJECTED"),
        ("truncated", "REJECTED"),
        ("malformed", "REJECTED"),
        ("invalid_action", "REJECTED"),
        ("unknown_evidence", "REJECTED"),
        ("injection", "REJECTED"),
    ],
)
async def test_provider_outcomes_and_core_continuity(tmp_path, mode, status):
    settings = configuration(tmp_path, ai_provider="fake", groq_timeout_seconds=0.05)
    fake = FakeProvider(mode)
    async with running(settings, fake) as (app, client):
        await client.create("manual", 42)
        await observe(client, 50)
        await wait_idle(app.state.core.ai)
        assert app.state.core.ai.status == status
        assert fake.calls == 1
        await advance(client)
        await observe(client, 52)
        a = await client.track()
        assert a["authorization"]["status"] == "UNKNOWN"
        assert a["recommendation"]["primary_action"] == "VERIFY_PERMISSION"
        assert (await client.http.get("/health/ready")).status_code == 200
        if mode == "success":
            assert a["ai_enrichment"]["model"] == "MOCK"
        else:
            assert a["ai_enrichment"] is None


@pytest.mark.parametrize("change_identity", [False, True])
async def test_blocked_provider_nonblocking_and_semantic_revalidation(tmp_path, change_identity):
    settings = configuration(tmp_path, ai_provider="fake")
    gate = asyncio.Event()
    fake = FakeProvider(gate=gate)
    async with running(settings, fake) as (app, client):
        await client.create("manual", 42)
        await observe(client, 50)
        await fake.entered.wait()
        for x in (52, 54, 56):
            await advance(client)
            await observe(client, x)
            assert (await client.http.get("/health/ready")).status_code == 200
        if change_identity:
            await client.bind("research_mission")
        gate.set()
        await wait_idle(app.state.core.ai)
        a = await client.track()
        assert (a["ai_enrichment"] is None) == change_identity
        if not change_identity:
            assert a["ai_enrichment"]["basis_revision"] <= a["core_revision"]


async def test_stop_cancels_pending_and_faults_are_mock(tmp_path):
    settings = configuration(
        tmp_path, ai_provider="fake", demo_faults_enabled=True, groq_timeout_seconds=0.03
    )
    fake = FakeProvider()
    async with running(settings, fake) as (app, client):
        await client.create("manual", 42)
        await client.request(
            "POST", "/v1/demo/faults", {"command_id": "fault", "fault": "AI_TIMEOUT", "enabled": True}
        )
        await observe(client, 50)
        await wait_idle(app.state.core.ai)
        assert app.state.core.ai.status == "TIMED_OUT"
        assert fake.calls == 0
        await client.command("stop")
        assert app.state.core.state["faults"] == {}


async def test_bounded_jobs_budget_and_no_retry_storm(tmp_path):
    settings = configuration(
        tmp_path,
        ai_provider="fake",
        ai_queue_capacity=2,
        groq_max_calls_per_session=1,
        ai_min_track_interval_seconds=0,
    )
    gate = asyncio.Event()
    fake = FakeProvider(gate=gate)
    async with running(settings, fake) as (app, client):
        await client.create("manual", 42)
        await observe(client, 50)
        await fake.entered.wait()
        for index in range(1, 10):
            await observe(client, 50, 50, f"track_{index}")
        assert len(app.state.core.ai.pending) <= 2
        gate.set()
        await wait_idle(app.state.core.ai)
        assert fake.calls == 1
        assert app.state.core.ai.counts["dropped"] > 0


async def test_retrieval_citations_and_narrow_schema(demo):
    app, client = demo
    await established(client)
    snapshot = make_snapshot(app.state.core.state, "track_01")
    assert snapshot["procedures"]
    result = await FakeProvider().complete(snapshot)
    assert validate_result(result.content, snapshot)["evidence_ids"]
    assert all(p["authority"] == "demo-authored" for p in snapshot["procedures"])
