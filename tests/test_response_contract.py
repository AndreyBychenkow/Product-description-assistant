"""Structured full prose output and safe handling of truncated model replies."""

import json

import httpx
import pytest
from conftest import FakeProvider
from openai import AsyncOpenAI

from product_assistant.config import Settings
from product_assistant.grounding import prepare_input
from product_assistant.prompts import initial_messages
from product_assistant.provider import (
    GenerationError,
    OpenAICompatibleProvider,
    ProviderReply,
    card_response_format,
)
from product_assistant.service import CardService


def test_full_schema_has_assignment_limits_and_only_known_ids(product):
    facts = prepare_input(product).facts
    output = card_response_format(initial_messages(facts))
    assert output["type"] == "json_schema" and output["json_schema"]["strict"]
    schema = output["json_schema"]["schema"]
    assert schema["properties"]["seo_title"]["maxLength"] == 70
    assert schema["properties"]["seo_description"]["minLength"] == 800
    assert schema["properties"]["seo_description"]["maxLength"] == 1200
    assert schema["properties"]["search_queries"]["maxItems"] == 5
    for field in schema["$defs"]["Evidence"]["properties"].values():
        assert field["items"]["enum"] == [fact.id for fact in facts]
        assert "F999" not in field["items"]["enum"]


@pytest.mark.parametrize("tokens", [0, 511, 16001])
def test_invalid_output_budget_is_rejected(tokens):
    with pytest.raises(ValueError):
        Settings(max_output_tokens=tokens)


def test_unknown_response_format_is_rejected():
    with pytest.raises(ValueError):
        Settings(response_format="unknown")


async def test_truncated_text_is_not_reused_as_assistant_context(product, good_card):
    truncated = '{"seo_description":"DO NOT CONTINUE THIS TRUNCATED TEXT'
    provider = FakeProvider(
        [
            ProviderReply(content=truncated, model="FIXTURE", finish_reason="length"),
            good_card,
        ]
    )
    result = await CardService(Settings(), provider).generate(product)
    assert result.validation.passed and result.metadata.attempts == 2
    assert not any(m["role"] == "assistant" for m in provider.messages[1])
    assert truncated not in json.dumps(provider.messages[1])
    assert "incomplete_response" in provider.messages[1][-1]["content"]


async def test_repeated_truncation_fails_closed_after_two_calls(product):
    cut = ProviderReply(
        content='{"seo_title":"unfinished', model="FIXTURE", finish_reason="length"
    )
    provider = FakeProvider([cut, cut])
    with pytest.raises(GenerationError) as caught:
        await CardService(Settings(), provider).generate(product)
    assert caught.value.code == "invalid_model_output" and provider.requests_used == 2


async def test_structured_api_contract_uses_configured_output_budget(
    monkeypatch, product, good_card
):
    def handler(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 4096
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"]
        assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0}
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "TEST-FIXTURE",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(good_card),
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
        base_url="https://openrouter.ai/api/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        "product_assistant.provider.AsyncOpenAI", lambda **kwargs: client
    )
    settings = Settings(
        app_mode="llm",
        backend="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-only",
        model="nvidia/nemotron-3.5-super-vl:free",
        response_format="json_schema",
    )
    provider = OpenAICompatibleProvider(settings)
    try:
        result = await CardService(settings, provider).generate(product)
        assert (
            result.validation.passed
            and result.metadata.generation_strategy == "free_text"
        )
    finally:
        await provider.close()


def test_trailing_measurement_without_unit_is_not_an_identity(product, good_card):
    from product_assistant.grounding import validate_card
    from product_assistant.schemas import LLMCard

    good_card["seo_title"] = "Пирометр testo 830-T1: температура -30 … +400"
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(issue.code == "unqualified_title_number" for issue in report.issues)


def test_model_number_and_complete_measurement_are_valid_title_endings(
    product, good_card
):
    from product_assistant.grounding import validate_card
    from product_assistant.schemas import LLMCard

    for title in ("Пирометр testo 830-T1", "Пирометр testo 830-T1 до +400 °C"):
        good_card["seo_title"] = title
        assert validate_card(
            LLMCard.model_validate(good_card), prepare_input(product).facts
        ).passed


def test_dangling_degree_symbol_is_rejected(product, good_card):
    from product_assistant.grounding import validate_card
    from product_assistant.schemas import LLMCard

    good_card["seo_title"] = "Пирометр testo 830-T1: -30 … +400 °"
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(issue.code == "incomplete_title_unit" for issue in report.issues)


@pytest.mark.parametrize(
    "bad_title",
    ["Пирометр testo 830-T1: -30 … +400", "Пирометр testo 830-T1: -30 … +400 °"],
)
async def test_only_broken_measurement_title_is_safely_restored(
    product, good_card, bad_title
):
    good_card["seo_title"] = bad_title
    provider = FakeProvider([good_card])
    result = await CardService(Settings(), provider).generate(product)
    assert result.validation.passed and result.seo_title == product.name
    assert result.evidence.seo_title == ["F001"]
    assert result.seo_description == good_card["seo_description"]
    assert result.metadata.attempts == 1
    assert any("исходное название" in item for item in result.warnings)
