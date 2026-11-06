"""All LLM responses in tests are labelled fixtures, never real examples."""

import copy
import json
import os
import socket
from pathlib import Path

import pytest

import product_assistant.config as config_module
from product_assistant.grounding import prepare_input
from product_assistant.provider import ProviderReply
from product_assistant.schemas import ProductInput

ROOT = Path(__file__).resolve().parent.parent

# Even collection must not read a developer's real .env or inherit API secrets.
CONFIG_ENV_KEYS = (
    "APP_MODE",
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_ATTEMPTS",
    "MAX_API_REQUESTS",
    "LLM_ALLOW_INSECURE_HTTP",
    "LLM_RESPONSE_FORMAT",
    "LLM_MAX_OUTPUT_TOKENS",
)
ORIGINAL_ENV = {key: os.environ.get(key) for key in CONFIG_ENV_KEYS}
for _key in CONFIG_ENV_KEYS:
    os.environ.pop(_key, None)
REAL_LOAD_DOTENV = config_module.load_dotenv
config_module.load_dotenv = lambda *args, **kwargs: False


@pytest.fixture(autouse=True)
def isolated_settings_and_network(monkeypatch, tmp_path):
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def load_test_env(*args, **kwargs):
        return REAL_LOAD_DOTENV(tmp_path / ".env", override=False, encoding="utf-8-sig")

    def forbidden_network(*args, **kwargs):
        pytest.fail("Unit tests must not access any real network or LLM API")

    monkeypatch.setattr(config_module, "load_dotenv", load_test_env)
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)


def pytest_sessionfinish(session, exitstatus):
    config_module.load_dotenv = REAL_LOAD_DOTENV
    for key, value in ORIGINAL_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def product() -> ProductInput:
    return ProductInput.model_validate_json(
        (ROOT / "examples/inputs/testo-830-t1.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def good_card(product) -> dict:
    # Intentionally artificial fixture: it tests contracts, not editorial quality.
    # It is never copied into examples/outputs or displayed as a real LLM answer.
    sentence = "Это тестовая заглушка только для автоматической проверки формата. "
    description = (sentence * 30)[:1000].rstrip()
    references = [fact.id for fact in prepare_input(product).facts]
    return {
        "seo_title": "Пирометр testo 830-T1",
        "seo_description": description,
        "search_queries": [
            "testo 830-T1",
            "пирометр testo 830-T1",
            "купить testo 830-T1",
        ],
        "commercial_block": {
            "audience": "Специалисты по измерению температуры поверхностей.",
            "tasks": "Бесконтактный контроль температуры.",
        },
        "evidence": {
            field: list(references)
            for field in (
                "seo_title",
                "seo_description",
                "search_queries",
                "commercial_block",
            )
        },
    }


class FakeProvider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests_used = 0
        self.messages = []

    async def complete(self, messages):
        self.requests_used += 1
        self.messages.append(copy.deepcopy(messages))
        if not self.replies:
            raise AssertionError("Unexpected call to fake provider")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, ProviderReply):
            return reply
        content = (
            reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        )
        return ProviderReply(
            content=content,
            model="TEST-FIXTURE-NOT-A-REAL-MODEL",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

    async def close(self):
        return None
