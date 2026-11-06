"""Demo checks and explicitly simulated API-contract tests: no LLM required."""

import argparse
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from product_assistant.__main__ import run
from product_assistant.app import create_app
from product_assistant.config import ROOT, Settings
from product_assistant.provider import GenerationError, OpenAICompatibleProvider
from product_assistant.service import CardService


def demo_settings():
    return Settings(
        app_mode="demo",
        backend="openai_compatible",
        base_url="http://127.0.0.1:1234/v1",
        model="",
    )


def clear_config(monkeypatch):
    for name in (
        "APP_MODE",
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_ALLOW_INSECURE_HTTP",
    ):
        monkeypatch.delenv(name, raising=False)


def test_env_defaults_to_demo_without_model(monkeypatch):
    clear_config(monkeypatch)
    settings = Settings.from_env()
    assert settings.app_mode == "demo"
    assert settings.backend == "openai_compatible"
    assert settings.model == ""
    assert not settings.can_generate


def test_explicit_customer_api_configuration(monkeypatch):
    clear_config(monkeypatch)
    monkeypatch.setenv("APP_MODE", "llm")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "CUSTOMER-MODEL-ID")
    monkeypatch.setenv("LLM_API_KEY", "test-token-not-real")
    settings = Settings.from_env()
    assert settings.can_generate
    assert settings.api_key == "test-token-not-real"
    assert "test-token-not-real" not in repr(settings)


def test_old_cache_does_not_automatically_connect_llm(monkeypatch, tmp_path):
    clear_config(monkeypatch)
    monkeypatch.setenv("LOCAL_LLM_CACHE", str(tmp_path))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "connection.json").write_text(
        json.dumps(
            {"token": "old-secret-test-only", "base_url": "http://127.0.0.1:8081/v1"}
        )
    )
    settings = Settings.from_env()
    assert settings.api_key == ""
    assert settings.app_mode == "demo"
    assert settings.base_url == "http://127.0.0.1:1234/v1"


@pytest.mark.parametrize("mode", ["auto", "download", ""])
def test_unknown_mode_is_rejected(mode):
    with pytest.raises(ValueError):
        Settings(app_mode=mode)


async def test_demo_never_constructs_api_sdk(monkeypatch, product):
    def forbidden(**kwargs):
        raise AssertionError("API client must not be constructed in demo")

    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", forbidden)
    provider = OpenAICompatibleProvider(demo_settings())
    with pytest.raises(GenerationError) as caught:
        await CardService(provider.settings, provider).generate(product)
    assert caught.value.code == "demo_mode"
    assert provider.requests_used == 0
    assert provider._client is None


def test_demo_inspection_and_saved_results_make_no_model_requests(monkeypatch, product):
    outgoing = AsyncMock(side_effect=AssertionError("No external network expected"))
    monkeypatch.setattr(httpx.AsyncClient, "send", outgoing)
    with TestClient(create_app(demo_settings())) as client:
        health = client.get("/health").json()
        assert health["app_mode"] == "demo"
        assert not health["can_generate"]
        assert health["llm_managed_by_app"] is False
        assert client.get("/").status_code == 200
        assert client.post("/api/inspect", json=product.model_dump()).status_code == 200
        for slug in ("testo-830-t1", "appa-62"):
            saved = client.get(f"/api/examples/{slug}/result").json()
            assert saved["origin"] == "saved_example"
            assert saved["result"]["metadata"]["mode"] == "llm"
            assert saved["result"]["validation"]["passed"]
        rejected = client.post("/api/generate", json=product.model_dump())
        assert rejected.status_code == 503
        assert rejected.json()["error"]["code"] == "demo_mode"
        assert "result" not in rejected.json()
        assert client.get("/health").json()["api_requests_used"] == 0
    outgoing.assert_not_awaited()


def test_demo_sparse_input_is_explained_without_llm():
    with TestClient(create_app(demo_settings())) as client:
        response = client.post("/api/generate", json={"name": "Прибор", "specs": {}})
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["status"] == "insufficient_data"
        assert result["metadata"]["attempts"] == 0


async def test_saved_cli_does_not_construct_provider(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved viewing must not instantiate a provider")

    monkeypatch.setattr(
        "product_assistant.__main__.OpenAICompatibleProvider", forbidden
    )
    status = await run(
        argparse.Namespace(
            saved_example="appa-62", input=None, format="json", output=None
        )
    )
    assert status == 0
    captured = capsys.readouterr()
    assert "СОХРАНЕННЫЙ" in captured.err
    expected = json.loads(
        (ROOT / "examples/outputs/appa-62.json").read_text(encoding="utf-8")
    )
    assert json.loads(captured.out) == expected


async def test_generic_api_contract_without_real_model(monkeypatch, product, good_card):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url == "https://customer-model.example/v1/chat/completions"
        assert payload["model"] == "CUSTOMER-MODEL-ID"
        assert payload["response_format"] == {"type": "json_object"}
        assert "thinking" not in payload
        assert "repeat_penalty" not in payload
        return httpx.Response(
            200,
            json={
                "id": "contract-fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "API-CONTRACT-TEST-FIXTURE",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(good_card, ensure_ascii=False),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
            },
        )

    client = AsyncOpenAI(
        api_key="test-only",
        base_url="https://customer-model.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "product_assistant.provider.AsyncOpenAI", lambda **kwargs: client
    )
    settings = Settings(
        app_mode="llm",
        backend="openai_compatible",
        base_url="https://customer-model.example/v1",
        model="CUSTOMER-MODEL-ID",
    )
    provider = OpenAICompatibleProvider(settings)
    try:
        result = await CardService(settings, provider).generate(product)
        assert result.validation.passed
        assert result.metadata.generation_strategy == "free_text"
        assert result.metadata.provider == "OpenAI-compatible API"
        assert len(requests) == 1
    finally:
        await provider.close()


async def test_empty_model_id_never_calls_api(monkeypatch):
    blocked = AsyncMock()
    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", blocked)
    provider = OpenAICompatibleProvider(
        Settings(app_mode="llm", backend="openai_compatible", model="")
    )
    with pytest.raises(GenerationError) as caught:
        await provider.complete([])
    assert caught.value.code == "llm_not_configured"
    blocked.assert_not_called()


def test_http_customer_server_requires_explicit_opt_in():
    with pytest.raises(ValueError):
        Settings(backend="openai_compatible", base_url="http://10.0.0.8:8001/v1")
    settings = Settings(
        backend="openai_compatible",
        base_url="http://10.0.0.8:8001/v1",
        allow_insecure_http=True,
    )
    assert settings.base_url.startswith("http://10.0.0.8")


def test_run_starts_only_application(monkeypatch):
    import run as launcher

    calls = []
    monkeypatch.setenv("APP_MODE", "llm")
    monkeypatch.setattr(
        launcher.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("No subprocess expected"),
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: pytest.fail("No download expected"),
    )
    assert launcher.main(["--mode", "demo", "--port", "8123"]) == 0
    assert calls == [
        (
            ("product_assistant.app:app",),
            {"host": "0.0.0.0", "port": 8123, "use_colors": False},
        )
    ]
    assert __import__("os").environ["APP_MODE"] == "demo"
