"""Exercise all simulator scenarios against an already-running local server."""

import argparse
import asyncio
from types import SimpleNamespace

import httpx

from harbor_engine.settings import Settings
from scripts.run_demo import DemoClient, run


async def verify(base_url, include_ai):
    settings = Settings()
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as http:
        client = DemoClient(http, settings)
        status = await client.request("GET", "/v1/status")
        if status["active_session_id"]:
            raise RuntimeError("An existing session is active; stop it explicitly first")
        scenarios = [
            "normal",
            "unknown_approach",
            "authorized_deviation",
            "sensor_loss",
            "identity_resolved",
            "replay_and_outlier",
            "malicious_note",
        ]
        if include_ai:
            # Attempt the fault before normal scenarios consume the real-time AI budget.
            scenarios.insert(0, "ai_failure")
        for scenario in scenarios:
            await run(
                SimpleNamespace(
                    base_url=base_url,
                    seed=42,
                    session_id=None,
                    scenario=scenario,
                    duration=45 if scenario != "sensor_loss" else 20,
                    clock="manual",
                )
            )
            status = await client.request("GET", "/v1/status")
            client.session_id = status["active_session_id"]
            assessment = await client.track()
            action = assessment["recommendation"]["primary_action"]
            authorization = assessment["authorization"]["status"]
            expected = {
                "normal": "MONITOR",
                "unknown_approach": "HUMAN_REVIEW",
                "authorized_deviation": "CONTACT_OPERATOR",
                "sensor_loss": "REQUEST_FRESH_OBSERVATION",
                "identity_resolved": "MONITOR",
                "replay_and_outlier": "VERIFY_PERMISSION",
                "malicious_note": "VERIFY_PERMISSION",
                "ai_failure": "HUMAN_REVIEW",
            }
            assert action == expected[scenario], (scenario, action, assessment["risk"])
            if scenario == "sensor_loss":
                assert assessment["capability"]["data_quality"] == "LOST"
                assert assessment["capability"]["source_health"] == "ONLINE"
            if scenario == "malicious_note":
                assert authorization == "UNKNOWN"
            if scenario == "ai_failure":
                assert assessment["capability"]["ai_status"] in ("UNAVAILABLE", "CIRCUIT_OPEN")
            print("VERIFIED", scenario, action, authorization)
            await client.command("stop")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--include-ai", action="store_true")
    args = parser.parse_args()
    asyncio.run(verify(args.base_url, args.include_ai))
