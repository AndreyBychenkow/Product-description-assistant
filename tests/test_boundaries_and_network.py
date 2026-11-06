from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from conftest import FakeProvider

from product_assistant.config import Settings
from product_assistant.grounding import prepare_input, validate_card
from product_assistant.provider import DeepSeekProvider, GenerationError
from product_assistant.schemas import LLMCard
from product_assistant.service import CardService


@pytest.mark.parametrize(
    "length,passed", [(800, True), (1200, True), (799, False), (1201, False)]
)
def test_description_boundaries_include_spaces(product, good_card, length, passed):
    good_card["seo_description"] = ("Тестовый текст. " * 100)[:length].rstrip()
    # Pad with a non-space character when the cut landed on a trailing space.
    good_card["seo_description"] += "а" * (length - len(good_card["seo_description"]))
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert report.passed is passed
    assert report.description_length == length


@pytest.mark.parametrize("length,passed", [(70, True), (71, False)])
def test_title_boundary(product, good_card, length, passed):
    good_card["seo_title"] = "А" * length
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert report.passed is passed


async def test_one_attempt_setting_does_not_retry(product, good_card):
    good_card["seo_description"] = "Слишком коротко."
    provider = FakeProvider([good_card])
    with pytest.raises(GenerationError):
        await CardService(Settings(max_attempts=1), provider).generate(product)
    assert provider.requests_used == 1


@pytest.mark.parametrize(
    "kind,expected",
    [("timeout", "provider_timeout"), ("connection", "provider_connection_error")],
)
async def test_network_errors_are_readable(monkeypatch, kind, expected):
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    error = (
        openai.APITimeoutError(request=request)
        if kind == "timeout"
        else openai.APIConnectionError(request=request)
    )
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=error))
        )
    )
    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", lambda **kwargs: fake)
    with pytest.raises(GenerationError) as caught:
        await DeepSeekProvider(Settings(api_key="test-secret")).complete([])
    assert caught.value.code == expected


async def test_empty_provider_choices_is_an_error(monkeypatch):
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(choices=[]))
            )
        )
    )
    monkeypatch.setattr("product_assistant.provider.AsyncOpenAI", lambda **kwargs: fake)
    with pytest.raises(GenerationError) as caught:
        await DeepSeekProvider(Settings(api_key="test-secret")).complete([])
    assert caught.value.code == "provider_empty_choices"
