"""Optional SDK contract checks; all HTTP is intercepted locally, never sent."""

import json

import httpx
import pytest
from conftest import configuration

from harbor_engine.ai.base import ProviderError
from harbor_engine.ai.groq_provider import GroqProvider
from harbor_engine.ai.worker import validate_result


@pytest.mark.parametrize(
    "status,category",
    [
        (200, None),
        (429, "RATE_LIMITED"),
        (500, "UNAVAILABLE"),
        (401, "MISCONFIGURED"),
        (404, "MISCONFIGURED"),
    ],
)
async def test_official_sdk_payload_without_network(tmp_path, status, category):
    groq = pytest.importorskip("groq")
    captured = []
    response = {
        "summary": "Review the evidence.",
        "suggested_next_evidence_action": "VERIFY_TRACK_IDENTITY",
        "evidence_ids": ["ev_identity_unconfirmed"],
        "procedure_ids": [],
        "uncertainties": ["Identity unknown"],
    }

    def handler(request):
        payload = json.loads(request.content)
        captured.append(payload)
        if status != 200:
            return httpx.Response(
                status,
                json={"error": {"message": "Synthetic provider error", "type": "test"}},
                headers={"retry-after": "45"},
            )
        return httpx.Response(
            200,
            json={
                "id": "synthetic_completion",
                "object": "chat.completion",
                "created": 1,
                "model": "openai/gpt-oss-20b",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(response)},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    settings = configuration(tmp_path)
    provider = GroqProvider.__new__(GroqProvider)
    provider.settings = settings
    provider.client = groq.AsyncGroq(
        api_key="synthetic-test-key",
        max_retries=0,
        timeout=1,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    snapshot = {
        "evidence_ids": ["ev_identity_unconfirmed"],
        "procedures": [],
        "eligible_next_evidence": ["VERIFY_TRACK_IDENTITY"],
        "synthetic_data": True,
    }
    try:
        if category:
            with pytest.raises(ProviderError) as error:
                await provider.complete(snapshot)
            assert error.value.category == category
            if status == 429:
                assert error.value.retry_after == 45
        else:
            result = await provider.complete(snapshot)
            assert result.usage == 30
            assert validate_result(result.content, snapshot) == response
        assert len(captured) == 1
        payload = captured[0]
        assert payload["stream"] is False
        assert payload["reasoning_effort"] == "low"
        schema = payload["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert set(schema["schema"]["required"]) == set(schema["schema"]["properties"])
        assert "tools" not in payload
    finally:
        await provider.close()
