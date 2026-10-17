"""On-demand Groq explanations private to a Streamlit session.

Never cache this object globally or attach its results to the shared engine.
The API supplies a bounded, read-only evidence snapshot and accepts no user key.
"""

import asyncio
import time
from collections import deque

from pydantic import SecretStr

from harbor_engine.ai.base import ProviderError
from harbor_engine.ai.groq_provider import GroqProvider
from harbor_engine.ai.worker import validate_result
from harbor_simulation.integration import DemoError


class PersonalAI:
    def __init__(self, key):
        self.key = SecretStr(key)
        self.calls = deque(maxlen=60)
        self.cooldown_until = 0
        self.last_track = {}
        self.results = {}
        self.error = None

    def wait_seconds(self, session_id=None, track_id=None):
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= 60:
            self.calls.popleft()
        until = self.cooldown_until
        if len(self.calls) >= 3:
            until = max(until, self.calls[0] + 60)
        if track_id:
            until = max(until, self.last_track.get((session_id, track_id), 0) + 30)
        return max(0, until - now)

    async def _complete(self, settings, snapshot, factory):
        provider = factory(settings)
        try:
            async with asyncio.timeout(settings.groq_timeout_seconds):
                result = await provider.complete(snapshot)
            return validate_result(result.content, snapshot)
        finally:
            await provider.close()

    def request(self, api, session_id, track_id, provider_factory=GroqProvider):
        """Call only from an explicit button action. Errors never include provider payloads."""
        self.error = None
        if self.wait_seconds(session_id, track_id) > 0:
            self.error = "Please wait for the AI cooldown, then request again."
            return
        path = f"/v1/sessions/{session_id}/tracks/{track_id}/explanation-context"
        try:
            before = api.request("GET", path)
            if not before["usable"]:
                self.error = "Fresh observations from an active exercise are needed for an explanation."
                return
            settings = api.settings.model_copy(update={"groq_api_key": self.key, "ai_provider": "groq"})
            now = time.monotonic()
            self.calls.append(now)
            self.last_track[(session_id, track_id)] = now
            response = asyncio.run(self._complete(settings, before["snapshot"], provider_factory))
            after = api.request("GET", path)
            if not after["usable"] or any(before[k] != after[k] for k in ("generation", "digest")):
                self.error = "The assessment changed during generation. Review the current CPU guidance."
                return
            # Bound memory; keep only the most recent private explanation.
            self.results = {(session_id, track_id): {
                "response": response,
                "basis_revision": before["core_revision"],
                "basis_assessed_at": before["assessed_at"],
                "model": settings.groq_model,
            }}
        except ProviderError as error:
            self.cooldown_until = time.monotonic() + error.retry_after
            self.error = {
                "RATE_LIMITED": "Groq rate limit reached for your key. Wait for the cooldown; no retry is scheduled.",
                "MISCONFIGURED": "Groq rejected this key or model. Check your account and replace the key if needed.",
                "UNAVAILABLE": "Groq is unavailable. CPU guidance remains available.",
            }.get(error.category, "Groq could not provide a usable explanation. CPU guidance remains available.")
        except (TimeoutError, asyncio.TimeoutError):
            self.cooldown_until = time.monotonic() + 30
            self.error = "Groq timed out. No automatic retry is scheduled."
        except DemoError:
            self.error = "The current engine evidence could not be retrieved. Check the exercise status."
        except Exception:
            self.cooldown_until = time.monotonic() + 30
            self.error = "The AI response could not be validated. Use the CPU assessment and try again later."
