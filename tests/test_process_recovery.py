"""Actual OS-process termination/restart, using a disposable local database."""

import asyncio
import os
import socket
import subprocess
import sys

import httpx
from conftest import configuration

from scripts.run_demo import DemoClient


async def test_committed_state_survives_process_restart(tmp_path):
    config = configuration(tmp_path)
    with socket.socket() as socket_reservation:
        socket_reservation.bind(("127.0.0.1", 0))
        port = socket_reservation.getsockname()[1]
    environment = {
        **os.environ,
        "DATABASE_PATH": config.database_path,
        "AI_PROVIDER": "off",
        "WEB_CONCURRENCY": "1",
        **{
            f"ENGINE_{role.upper()}_TOKEN": getattr(config, f"engine_{role}_token").get_secret_value()
            for role in ("sensor", "operator", "viewer")
        },
    }
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "harbor_engine.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
        "--no-access-log",
    ]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log = open(tmp_path / "process.log", "w", encoding="utf-8")
    process = None

    async def start(http):
        worker = subprocess.Popen(command, env=environment, stdout=log, stderr=log, creationflags=flags)
        try:
            async with asyncio.timeout(20):
                while True:
                    if worker.poll() is not None:
                        raise AssertionError("Test server exited before readiness")
                    try:
                        if (await http.get("/health/ready")).status_code == 200:
                            return worker
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.05)  # Bounded readiness polling, not simulated scenario time.
        except BaseException:
            worker.terminate()
            worker.wait(timeout=10)
            raise

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=1) as http:
            process = await start(http)
            client = DemoClient(http, config)
            session = await client.create("manual", 42)
            event = await client.observation(session["current_time"], 50, 50)
            before = await client.track()
            process.terminate()
            process.wait(timeout=10)
            process = await start(http)
            after = await client.track()
            assert after["estimate"] == before["estimate"]
            assert after["incident"]["incident_id"] == before["incident"]["incident_id"]
            assert (await client.send(event))["disposition"] == "DUPLICATE"
            assert (await client.metadata())["current_time"] == session["current_time"]
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        log.close()
