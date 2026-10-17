"""Measured HTTP workload: normal and burst phases, fresh timestamps, bounded clients."""

import argparse
import asyncio
import json
import os
import platform
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

from harbor_engine.settings import Settings
from scripts.run_demo import DemoClient


async def phase(client, duration, rate, tracks):
    latencies, outcomes = [], Counter()
    started = time.monotonic()
    semaphore = asyncio.Semaphore(320)
    outstanding = set()

    async def send(index):
        async with semaphore:
            t = time.monotonic() - started
            when = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            event = client.event(
                when,
                "observation",
                {
                    "track_id": f"bench_{index % tracks:02}",
                    "coordinate_frame": "harbor_local_m",
                    "x_m": 50 + t * 0.1,
                    "y_m": 30 + index % tracks * 2,
                    "position_sigma_m": 2,
                    "claimed_vehicle_id": None,
                },
            )
            before = time.perf_counter()
            try:
                response = await client.http.post(
                    f"/v1/sessions/{client.session_id}/events", json=event, headers=client.headers("sensor")
                )
                record = response.json()
                outcomes[
                    record.get("disposition", record.get("error", {}).get("code", str(response.status_code)))
                ] += 1
            except (httpx.HTTPError, ValueError):
                outcomes["CLIENT_TIMEOUT_OR_ERROR"] += 1
            latencies.append((time.perf_counter() - before) * 1000)

    for index in range(round(duration * rate)):
        await asyncio.sleep(max(0, started + index / rate - time.monotonic()))
        if len(outstanding) >= 512:
            outcomes["CLIENT_ADMISSION_DROPPED"] += 1
            continue
        task = asyncio.create_task(send(index))
        outstanding.add(task)
        task.add_done_callback(outstanding.discard)
    if outstanding:
        await asyncio.gather(*outstanding)
    return {
        "requested_duration_seconds": duration,
        "actual_seconds": time.monotonic() - started,
        "requested_observations_per_second": rate,
        "attempted_requests": len(latencies),
        "client_concurrency_limit": 320,
        "client_pending_limit": 512,
        "http_ingest_ms": {
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
            "p99": float(np.percentile(latencies, 99)),
            "max": max(latencies),
        },
        "outcomes": dict(outcomes),
    }


async def run(args):
    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=30,
        limits=httpx.Limits(max_connections=320, max_keepalive_connections=40),
    ) as http:
        client = DemoClient(http, Settings())
        status = await client.request("GET", "/v1/status")
        if status["ai"]["provider"] != "off":
            raise RuntimeError("Baseline requires AI_PROVIDER=off")
        report = {
            "synthetic_data": True,
            "ai_provider": "off",
            "python": platform.python_version(),
            "os": platform.platform(),
            "cpu": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "memory_observation": "not available without optional OS tooling",
        }
        for label, duration, rate in (
            ("normal", args.duration, args.tracks * args.hz),
            ("burst", args.burst_duration, args.burst_rate),
        ):
            await client.create("realtime", args.seed, "Synthetic benchmark " + label)
            report[label] = await phase(client, duration, rate, args.tracks)
            report[label]["server_metrics"] = await client.request("GET", "/v1/metrics")
            await client.command("stop")
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--tracks", type=int, default=20)
    parser.add_argument("--hz", type=float, default=1)
    parser.add_argument("--burst-duration", type=float, default=5)
    parser.add_argument("--burst-rate", type=float, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="runtime/benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.tracks <= 20 or min(args.duration, args.hz, args.burst_duration, args.burst_rate) <= 0:
        parser.error("positive durations/rates and 1..20 tracks required")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
