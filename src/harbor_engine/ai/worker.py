import asyncio
import copy
import json
import time
import uuid
from collections import OrderedDict, deque
from contextlib import suppress

from pydantic import ValidationError

from ..clock import stamp, utc_now
from ..errors import DomainError
from ..retrieval import retrieve
from ..schemas import AIResponse
from .base import ProviderError
from .fake_provider import inject_fault


def make_snapshot(state, track_id):
    track = state["tracks"][track_id]
    assessment = track["assessment"]
    records = retrieve(state["procedures"], assessment, state["policy"]["procedure_version"])
    snapshot = {
        "synthetic_data": True,
        "policy_version": assessment["policy_version"],
        "reason_codes": assessment["risk"]["reason_codes"],
        "primary_action": assessment["recommendation"]["primary_action"],
        "authorization": assessment["authorization"]["status"],
        "eligible_next_evidence": assessment["recommendation"]["eligible_next_evidence"],
        "evidence_ids": [e["evidence_id"] for e in assessment["evidence"]],
        "uncertainty": {
            "observation_age_seconds": assessment["source"]["observation_age_seconds"],
            "zone_entries": assessment["forecast"]["zone_entries"],
            "calibrated": False,
        },
        "procedures": [{**p, "text": p["text"][:500]} for p in records],
        "untrusted_operator_note": track.get("note", {}).get("text", "")[:500],
    }
    if len(json.dumps(snapshot).encode()) > 10000:
        snapshot["procedures"] = []
        snapshot["untrusted_operator_note"] = ""
    return snapshot


def validate_result(content, snapshot):
    result = AIResponse.model_validate_json(content)
    if not result.evidence_ids or not set(result.evidence_ids) <= set(snapshot["evidence_ids"]):
        raise ValueError("Evidence outside supplied snapshot")
    if not set(result.procedure_ids) <= {p["procedure_id"] for p in snapshot["procedures"]}:
        raise ValueError("Procedure outside supplied snapshot")
    if (
        result.suggested_next_evidence_action is not None
        and result.suggested_next_evidence_action not in snapshot["eligible_next_evidence"]
    ):
        raise ValueError("Ineligible next evidence")
    return result.model_dump()


class AIWorker:
    def __init__(self, settings, coordinator, provider=None):
        self.settings, self.core, self.provider = settings, coordinator, provider
        self.pending = OrderedDict()
        self.wake = asyncio.Event()
        self.calls = deque(maxlen=120)
        self.track_last = {}
        self.failures = 0
        self.cooldown = 0
        self.disabled = False
        self.status = (
            "OFF" if settings.ai_provider == "off" else "MOCK" if settings.ai_provider == "fake" else "READY"
        )
        self.task = self.inflight = None
        self.counts = {"attempted": 0, "accepted": 0, "rejected": 0, "dropped": 0, "coalesced": 0}
        self.latencies = deque(maxlen=100)

    async def start(self):
        if self.settings.ai_provider == "off":
            return
        if self.provider is None:
            try:
                if self.settings.ai_provider == "fake":
                    from .fake_provider import FakeProvider

                    self.provider = FakeProvider()
                else:
                    if not self.settings.groq_api_key.get_secret_value():
                        raise ValueError("Missing key")
                    from .groq_provider import GroqProvider

                    self.provider = GroqProvider(self.settings)
            except (ImportError, ValueError):
                self.status = "MISCONFIGURED"
                self.disabled = True
        self.task = asyncio.create_task(self.run(), name="ai-worker")

    def new_session(self):
        self.cancel_session()
        self.track_last.clear()
        self.failures = 0
        # Account misconfiguration needs a restart; global rate/cooldown budgets persist.

    def cancel_session(self):
        self.pending.clear()
        if self.inflight:
            self.inflight.cancel()
        if self.status == "PENDING":
            self.status = "MOCK" if self.settings.ai_provider == "fake" else "READY"

    def schedule(self, state, track_id):
        if self.settings.ai_provider == "off" or self.disabled:
            return
        job = {
            "session_id": state["session_id"],
            "generation": state["generation"],
            "track_id": track_id,
            "digest": state["tracks"][track_id]["digest"],
            "snapshot": make_snapshot(state, track_id),
            "basis_revision": state["tracks"][track_id]["assessment"]["core_revision"],
            "basis_assessed_at": state["tracks"][track_id]["assessment"]["assessed_at"],
            "urgent": state["tracks"][track_id]["assessment"]["risk"]["current_band"] == "HIGH",
        }
        if track_id in self.pending:
            self.counts["coalesced"] += 1
        elif len(self.pending) >= self.settings.ai_queue_capacity:
            nonurgent = next((key for key, value in self.pending.items() if not value["urgent"]), None)
            if job["urgent"] and nonurgent:
                self.pending.pop(nonurgent)
            else:
                self.counts["dropped"] += 1
                return
        self.pending[track_id] = copy.deepcopy(job)
        self.wake.set()

    async def run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while self.pending:
                key = next(
                    (key for key, value in self.pending.items() if value["urgent"]), next(iter(self.pending))
                )
                job = self.pending.pop(key)
                self.inflight = asyncio.create_task(self.process(job))
                try:
                    await self.inflight
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    self.inflight = None

    async def process(self, job):
        now = time.monotonic()
        while self.calls and now - self.calls[0][0] >= 60:
            self.calls.popleft()
        estimate = (
            (len(json.dumps(job["snapshot"])) + len(json.dumps(AIResponse.model_json_schema()))) // 3
            + self.settings.groq_max_completion_tokens
            + 256
        )
        if (
            self.disabled
            or now < self.cooldown
            or len(self.calls) >= self.settings.groq_max_calls_per_minute
            or sum(c[1] for c in self.calls) + estimate > self.settings.groq_soft_token_budget_per_minute
            or now - self.track_last.get(job["track_id"], -1e12) < self.settings.ai_min_track_interval_seconds
        ):
            self.counts["dropped"] += 1
            return
        job_id = "ai_" + uuid.uuid4().hex
        base = {k: job[k] for k in ("track_id", "digest", "generation")}
        base["job_id"] = job_id
        try:
            await self.core.submit("ai_start", job["session_id"], base)
        except DomainError:
            self.counts["dropped"] += 1
            return
        self.calls.append([now, estimate])
        usage_entry = self.calls[-1]
        self.track_last[job["track_id"]] = now
        self.counts["attempted"] += 1
        self.status = "PENDING"
        enrichment = None
        usage = None
        try:
            faults = self.core.state["faults"]
            fault = next((name for name, until in faults.items() if until > utc_now()), None)
            async with asyncio.timeout(self.settings.groq_timeout_seconds):
                result = (
                    await inject_fault(fault, job["snapshot"])
                    if fault
                    else await self.provider.complete(job["snapshot"])
                )
            validated = validate_result(result.content, job["snapshot"])
            usage = result.usage
            if usage is not None:
                usage_entry[1] = max(0, usage)
            enrichment = {
                "schema_version": "1.0",
                "enrichment_id": job_id,
                "basis_revision": job["basis_revision"],
                "basis_assessed_at": job["basis_assessed_at"],
                "created_at": stamp(utc_now()),
                "provider": self.settings.ai_provider,
                "model": "MOCK" if self.settings.ai_provider == "fake" else self.settings.groq_model,
                "validation_status": "STRUCTURE_AND_REFERENCES_VALIDATED",
                "review_required": True,
                "response": validated,
            }
            self.status = "MOCK" if self.settings.ai_provider == "fake" else "READY"
            self.failures = 0
        except TimeoutError:
            self.failed("TIMED_OUT", 30)
        except ProviderError as error:
            self.failed(error.category, error.retry_after)
        except (ValidationError, ValueError, TypeError):
            self.failed("REJECTED", 30)
        except Exception:
            self.failed("UNAVAILABLE", 30)
        self.latencies.append((time.monotonic() - now) * 1000)
        try:
            attached = await self.core.submit(
                "ai_result",
                job["session_id"],
                {
                    **base,
                    "started_mono": now,
                    "enrichment": enrichment,
                    "status": self.status,
                    "usage": usage,
                },
            )
            self.counts["accepted" if attached["status"] == "ATTACHED" else "rejected"] += 1
        except DomainError:
            self.counts["rejected"] += 1

    def failed(self, category, cooldown):
        self.failures += 1
        self.status = category
        self.cooldown = time.monotonic() + cooldown
        if category == "MISCONFIGURED":
            self.disabled = True
        elif self.failures >= 3:
            self.status = "CIRCUIT_OPEN"
            self.cooldown = time.monotonic() + max(60, cooldown)

    def metrics(self):
        return {
            "status": self.status,
            "provider": self.settings.ai_provider,
            "mock": self.settings.ai_provider == "fake",
            "pending": len(self.pending),
            "counters": dict(self.counts),
            "cooldown_seconds": max(0, self.cooldown - time.monotonic()),
            "last_latency_ms": self.latencies[-1] if self.latencies else None,
        }

    async def close(self):
        self.cancel_session()
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.provider:
            await self.provider.close()
