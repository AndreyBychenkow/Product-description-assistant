"""Connection helper and Windows .env encoding: deterministic, offline tests."""

import pytest

from product_assistant.config import Settings
from product_assistant.provider import ProviderReply
from scripts import check_connection


async def test_connection_helper_in_demo_never_creates_provider(monkeypatch, capsys):
    monkeypatch.setattr(Settings, "from_env", lambda: Settings(app_mode="demo"))

    def forbidden(*args, **kwargs):
        raise AssertionError("No provider expected in demo")

    monkeypatch.setattr(check_connection, "OpenAICompatibleProvider", forbidden)
    assert await check_connection.check() == 2
    assert "модель не вызывалась" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text,exit_code",
    [('{"status":"ok"}', 0), ('{"status":"unexpected"}', 1), ("not JSON", 1)],
)
async def test_connection_helper_accepts_only_complete_expected_json(
    monkeypatch, text, exit_code
):
    settings = Settings(app_mode="llm", api_key="test-only")
    monkeypatch.setattr(Settings, "from_env", lambda: settings)
    closed = []

    class TestProvider:
        def __init__(self, config):
            pass

        async def complete(self, messages):
            return ProviderReply(
                content=text, model="FIXTURE", usage={}, finish_reason="stop"
            )

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(check_connection, "OpenAICompatibleProvider", TestProvider)
    assert await check_connection.check() == exit_code
    assert closed == [True]


def test_windows_utf8_bom_env_is_supported(monkeypatch, tmp_path):
    monkeypatch.setattr("product_assistant.config.ROOT", tmp_path)
    for key in ("APP_MODE", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "APP_MODE=llm\nLLM_PROVIDER=openai_compatible\nLLM_BASE_URL=https://openrouter.ai/api/v1\nLLM_MODEL=TEST-FIXTURE\nLLM_API_KEY=fake-test-only\n",
        encoding="utf-8-sig",
    )
    # load_dotenv writes to os.environ; register those keys for proper teardown.
    import os

    before = dict(os.environ)
    try:
        settings = Settings.from_env()
        assert settings.app_mode == "llm" and settings.can_generate
        assert settings.api_key == "fake-test-only"
    finally:
        for key in (
            "APP_MODE",
            "LLM_PROVIDER",
            "LLM_BASE_URL",
            "LLM_MODEL",
            "LLM_API_KEY",
        ):
            if key in before:
                os.environ[key] = before[key]
            else:
                os.environ.pop(key, None)
