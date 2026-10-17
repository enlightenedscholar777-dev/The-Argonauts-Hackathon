import asyncio
import json

from .base import ProviderError, ProviderResult


class FakeProvider:
    """Explicit MOCK adapter, also injectable for deterministic failure tests."""

    def __init__(self, mode="success", gate=None):
        self.mode = mode
        self.gate = gate
        self.entered = asyncio.Event()
        self.calls = 0

    async def complete(self, snapshot):
        self.calls += 1
        self.entered.set()
        if self.gate:
            await self.gate.wait()
        if self.mode in ("timeout", "block"):
            await asyncio.Event().wait()
        if self.mode in ("rate_limit", "unavailable", "credentials", "missing_model", "server_error"):
            raise ProviderError(
                {
                    "rate_limit": "RATE_LIMITED",
                    "credentials": "MISCONFIGURED",
                    "missing_model": "MISCONFIGURED",
                }.get(self.mode, "UNAVAILABLE")
            )
        if self.mode in ("refusal", "truncated", "malformed"):
            return ProviderResult("{bad json")
        eligible = snapshot["eligible_next_evidence"]
        response = {
            "summary": "MOCK: Review the supplied deterministic evidence and verify the remaining uncertainty.",
            "suggested_next_evidence_action": eligible[0] if eligible else None,
            "evidence_ids": snapshot["evidence_ids"][:1],
            "procedure_ids": [p["procedure_id"] for p in snapshot["procedures"][:1]],
            "uncertainties": ["Synthetic observations and demo policy only."],
        }
        if self.mode == "invalid_action":
            response["suggested_next_evidence_action"] = "CONTROL_VEHICLE"
        if self.mode == "unknown_evidence":
            response["evidence_ids"] = ["invented"]
        if self.mode == "injection":
            response["authorization"] = "AUTHORIZED"
        return ProviderResult(json.dumps(response), 150)

    async def close(self):
        pass


async def inject_fault(name, snapshot):
    modes = {
        "AI_UNAVAILABLE": "unavailable",
        "AI_TIMEOUT": "timeout",
        "AI_RATE_LIMIT": "rate_limit",
        "AI_INVALID_RESPONSE": "invalid_action",
    }
    return await FakeProvider(modes[name]).complete(snapshot)
