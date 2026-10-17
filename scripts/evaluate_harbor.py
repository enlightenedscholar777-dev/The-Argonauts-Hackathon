"""Reproducible synthetic evidence; no Groq calls or external operational data."""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from harbor_engine.main import create_app
from harbor_engine.settings import Settings
from harbor_simulation.integration import DemoController, EngineAPI


def run(output):
    report = {
        "scope": "Synthetic scenarios through the real engine API using in-process ASGI transport; CPU-only, no human baseline or real-world safety claim",
        "ai_provider": "off",
        "scenarios": {},
    }
    with tempfile.TemporaryDirectory(prefix="harbor-evaluation-") as scratch:
        settings = Settings(
            _env_file=None,
            database_path=str(Path(scratch) / "eval.sqlite3"),
            ai_provider="off",
            groq_api_key="",
            engine_sensor_token="sensor_" + "s" * 32,
            engine_operator_token="operator_" + "o" * 32,
            engine_viewer_token="viewer_" + "v" * 32,
        )
        with TestClient(create_app(settings)) as http:
            demo = DemoController(EngineAPI("http://127.0.0.1", settings, http=http), background=False)
            for name, seconds in [
                ("Harbor approach", 60),
                ("Sensor outage", 32),
                ("Port operations disruption", 55),
                ("Harbor-wide operations", 35),
            ]:
                demo.start(name, autoplay=False, traffic_count=48)
                timing, first_high, first_entry, first_stale, first_lost = [], None, None, None, None
                for second in range(seconds + 1):
                    if second:
                        started = time.perf_counter()
                        demo.step()
                        timing.append((time.perf_counter() - started) * 1000)
                    snap = demo.api.snapshot(demo.session_id)
                    for track in snap["tracks"]:
                        if track["track_id"] == "unknown_01":
                            if track["risk"]["current_band"] == "HIGH" and first_high is None:
                                first_high = second
                            if track["forecast"]["current_zones"] and first_entry is None:
                                first_entry = second
                        if track["capability"]["data_quality"] == "STALE" and first_stale is None:
                            first_stale = second
                        if track["capability"]["data_quality"] == "LOST" and first_lost is None:
                            first_lost = second
                view = demo.view()
                report["scenarios"][name] = {
                    "scenario_seconds": seconds,
                    "first_high_concern_s": first_high,
                    "first_estimated_zone_entry_s": first_entry,
                    "warning_lead_seconds": first_entry - first_high
                    if first_entry is not None and first_high is not None
                    else None,
                    "first_stale_s": first_stale,
                    "first_lost_s": first_lost,
                    "core_ready": demo.api.status()["core"],
                    "surface_observations_accepted": view["counts"].get("SURFACE_OBSERVATIONS", 0),
                    "sonar_contacts": len(snap["tracks"]),
                    "surface_vessels": snap["surface"]["observations"],
                    "surface_advisories": snap["surface"]["alerts"],
                    "ingestion_step_ms_p50": round(statistics.median(timing), 2),
                    "ingestion_step_ms_p95": round(sorted(timing)[int(0.95 * (len(timing) - 1))], 2),
                    "model_pair_checks_per_step": snap["surface"]["pairs_evaluated"],
                }
                demo.stop(demo.session_id)
            demo.close()
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/harbor-evaluation.json")
    run(parser.parse_args().output)
