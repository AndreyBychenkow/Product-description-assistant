from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from conftest import FakeProvider
from fastapi.testclient import TestClient

from product_assistant.app import create_app
from product_assistant.config import Settings
from product_assistant.provider import DeepSeekProvider, GenerationError


def test_health_does_not_disclose_key():
    app = create_app(Settings(api_key="test-secret"), FakeProvider([]))
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["api_key_configured"] is True
        assert "test-secret" not in response.text


@pytest.mark.parametrize(
    "body", ["{broken json", "[]", "{}", '{"name": "", "specs": []}']
)
def test_api_rejects_bad_input(body):
    with TestClient(create_app(Settings(), FakeProvider([]))) as client:
        response = client.post(
            "/api/generate", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_input"


def test_api_rejects_oversized_body():
    with TestClient(create_app(Settings(), FakeProvider([]))) as client:
        response = client.post("/api/inspect", content="x" * (129 * 1024))
        assert response.status_code == 413


def test_inspection_is_available_without_key(product):
    provider = FakeProvider([])
    with TestClient(create_app(Settings(), provider)) as client:
        response = client.post("/api/inspect", json=product.model_dump())
        assert response.status_code == 200
        assert response.json()["fact_count"] > 10
        assert "specs.Погрешность" in response.json()["missing_fields"]
        assert provider.requests_used == 0


def test_api_success_has_json_and_markdown(product, good_card):
    with TestClient(create_app(Settings(), FakeProvider([good_card]))) as client:
        response = client.post("/api/generate", json=product.model_dump())
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["validation"]["passed"]
        assert "## SEO-описание" in data["markdown"]


def test_balance_error_is_explicit_and_no_fake_result(product):
    provider = FakeProvider(
        [
            GenerationError(
                503,
                "provider_insufficient_balance",
                "DeepSeek: HTTP 402, недостаточно средств",
            )
        ]
    )
    with TestClient(create_app(Settings(), provider)) as client:
        response = client.post("/api/generate", json=product.model_dump())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_insufficient_balance"
        assert "result" not in response.json()


def test_web_form_and_examples():
    with TestClient(create_app(Settings(), FakeProvider([]))) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "ТехРедактор" in page.text
        assert "innerHTML" not in page.text
        assert "X-Frame-Options" not in page.headers
        assert client.get("/api/examples").json()["items"][1]["id"] == "appa-62"
        assert client.get("/api/examples/testo-830-t1").status_code == 200
        assert client.get("/api/examples/unknown").status_code == 404


async def test_missing_key_never_calls_sdk(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("SDK must not be called")

    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", unexpected)
    with pytest.raises(GenerationError) as caught:
        await DeepSeekProvider(Settings()).complete([])
    assert caught.value.code == "api_key_missing"


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "provider_auth_error"),
        (403, "provider_auth_error"),
        (402, "provider_insufficient_balance"),
        (429, "provider_rate_limit"),
        (500, "provider_error"),
    ],
)
async def test_upstream_errors_are_sanitized(monkeypatch, status, expected):
    response = httpx.Response(
        status,
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )
    error = openai.APIStatusError(
        "sensitive-provider-message",
        response=response,
        body={"private": "sensitive-provider-message"},
    )
    create = AsyncMock(side_effect=error)
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", lambda **kwargs: fake)
    with pytest.raises(GenerationError) as caught:
        await DeepSeekProvider(Settings(api_key="test-secret")).complete([])
    assert caught.value.code == expected
    assert "sensitive-provider-message" not in str(caught.value)
    assert "test-secret" not in str(caught.value)
    assert create.await_count == 1


async def test_process_budget_is_enforced(monkeypatch):
    response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    )
    create = AsyncMock(
        side_effect=openai.APIStatusError("rate limit", response=response, body={})
    )
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", lambda **kwargs: fake)
    provider = DeepSeekProvider(Settings(api_key="test-secret", max_api_requests=1))
    with pytest.raises(GenerationError):
        await provider.complete([])
    with pytest.raises(GenerationError) as caught:
        await provider.complete([])
    assert caught.value.code == "session_budget_exceeded"
    assert create.await_count == 1
