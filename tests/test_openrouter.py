"""OpenRouter integration contract: simulated HTTP, never uses a real key."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from product_assistant.config import Settings
from product_assistant.provider import GenerationError, OpenAICompatibleProvider


def router_settings(**overrides):
    values = dict(
        app_mode="llm",
        backend="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        model="nvidia/nemotron-3.5-super-vl:free",
        api_key="test-only-not-a-real-key",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    "host", ["openrouter.ai", "eu.openrouter.ai", "us.openrouter.ai"]
)
def test_openrouter_detection(host):
    settings = router_settings(base_url=f"https://{host}/api/v1")
    assert settings.is_openrouter
    assert settings.api_key_required
    assert settings.provider_name == "OpenRouter"
    assert settings.can_generate


def test_lookalike_hostname_is_not_openrouter():
    assert not router_settings(base_url="https://notopenrouter.ai/v1").is_openrouter


async def test_missing_key_cannot_start_generation(monkeypatch):
    blocked = AsyncMock()
    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", blocked)
    provider = OpenAICompatibleProvider(router_settings(api_key=""))
    assert not provider.settings.can_generate
    with pytest.raises(GenerationError) as caught:
        await provider.complete([])
    assert caught.value.code == "api_key_missing"
    assert provider.requests_used == 0
    blocked.assert_not_called()


async def test_free_route_forbids_paid_endpoints_and_has_no_key_in_prompt(monkeypatch):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.headers["authorization"] == "Bearer test-only-not-a-real-key"
        assert b"test-only-not-a-real-key" not in request.content
        assert payload["model"] == "nvidia/nemotron-3.5-super-vl:free"
        assert payload["provider"]["max_price"] == {"prompt": 0, "completion": 0}
        assert payload["reasoning"] == {"enabled": False}
        assert payload["response_format"] == {"type": "json_object"}
        assert "models" not in payload and "thinking" not in payload
        return httpx.Response(
            200,
            json={
                "id": "test-fixture",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"status":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 5,
                    "total_tokens": 10,
                },
            },
        )

    client = AsyncOpenAI(
        api_key="test-only-not-a-real-key",
        base_url="https://openrouter.ai/api/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "product_assistant.provider.AsyncOpenAI", lambda **kwargs: client
    )
    provider = OpenAICompatibleProvider(router_settings())
    try:
        reply = await provider.complete([{"role": "user", "content": "Return JSON."}])
        assert json.loads(reply.content) == {"status": "ok"}
        assert len(requests) == 1
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_auth_error"),
        (402, "provider_insufficient_balance"),
        (429, "provider_rate_limit"),
    ],
)
async def test_router_errors_never_fallback_or_mention_wrong_provider(
    monkeypatch, status, code
):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "private provider diagnostic must not leak",
                    "code": status,
                }
            },
        )

    client = AsyncOpenAI(
        api_key="test-only-not-a-real-key",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "product_assistant.provider.AsyncOpenAI", lambda **kwargs: client
    )
    provider = OpenAICompatibleProvider(router_settings())
    try:
        with pytest.raises(GenerationError) as caught:
            await provider.complete([{"role": "user", "content": "Return JSON."}])
        assert caught.value.code == code
        assert "OpenRouter" in caught.value.message
        assert "DeepSeek" not in caught.value.message
        assert "private provider diagnostic" not in caught.value.message
        assert len(requests) == 1
    finally:
        await provider.close()
