"""Explicit opt-in account/schema check. At most one tiny completion."""

import asyncio
import time

from harbor_engine.ai.base import ProviderError
from harbor_engine.ai.worker import validate_result
from harbor_engine.settings import Settings


async def check():
    settings = Settings()
    if not settings.groq_api_key.get_secret_value():
        print("SKIPPED: no GROQ_API_KEY configured. Offline engine remains usable.")
        return
    try:
        from harbor_engine.ai.groq_provider import GroqProvider

        provider = GroqProvider(settings)
    except (ImportError, ValueError):
        print("MISCONFIGURED: install the groq extra and configure the key locally.")
        return
    began = time.monotonic()
    usage = None
    try:
        try:
            async with asyncio.timeout(settings.groq_timeout_seconds):
                models = await provider.client.models.list()
            print("Accessible model IDs:", ", ".join(model.id for model in models.data))
        except Exception:
            print("Model listing unavailable; attempting the single configured functional check.")
        snapshot = {
            "synthetic_data": True,
            "reason_codes": ["IDENTITY_UNCONFIRMED"],
            "primary_action": "VERIFY_PERMISSION",
            "authorization": "UNKNOWN",
            "eligible_next_evidence": ["VERIFY_TRACK_IDENTITY"],
            "evidence_ids": ["ev_identity_unconfirmed"],
            "procedures": [],
            "uncertainty": "Identity unverified",
        }
        async with asyncio.timeout(settings.groq_timeout_seconds):
            result = await provider.complete(snapshot)
        usage = result.usage
        validate_result(result.content, snapshot)
        print(f"Model={settings.groq_model} SUCCESS")
    except ProviderError as error:
        print(f"Model={settings.groq_model} {error.category}; deterministic fallback remains available")
    except TimeoutError:
        print(f"Model={settings.groq_model} TIMED_OUT")
    except Exception:
        print(f"Model={settings.groq_model} REJECTED_RESPONSE")
    finally:
        print(f"Check latency_ms={(time.monotonic() - began) * 1000:.1f} reported_tokens={usage}")
        await provider.close()


if __name__ == "__main__":
    asyncio.run(check())
