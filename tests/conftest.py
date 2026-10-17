from contextlib import asynccontextmanager

import httpx
import pytest

from harbor_engine.main import create_app
from harbor_engine.settings import Settings
from scripts.run_demo import DemoClient


def configuration(tmp_path, **kwargs):
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "test.sqlite3"),
        engine_sensor_token="sensor_" + "s" * 32,
        engine_operator_token="operator_" + "o" * 32,
        engine_viewer_token="viewer_" + "v" * 32,
        **kwargs,
    )


@asynccontextmanager
async def running(settings, provider=None, storage=None):
    app = create_app(settings, provider=provider, storage=storage)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=5
        ) as http:
            yield app, DemoClient(http, settings)


@pytest.fixture
async def demo(tmp_path):
    async with running(configuration(tmp_path)) as pair:
        await pair[1].create("manual", 42)
        yield pair


async def advance(client, seconds=1):
    return await client.command("clock/advance", {"delta_seconds": seconds})


async def observe(client, x, y=50, track_id="track_01"):
    session = await client.metadata()
    return await client.observation(session["current_time"], x, y, track_id)


async def established(client, x=50, y=50, vx=2):
    for i in range(4):
        if i:
            await advance(client)
        await observe(client, x + i * vx, y)
    return await client.track()
