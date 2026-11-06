import copy

import pytest
from conftest import FakeProvider

from product_assistant.config import Settings
from product_assistant.grounding import prepare_input, validate_card
from product_assistant.local_rendering import assemble_local_card
from product_assistant.prompts import local_messages
from product_assistant.provider import GenerationError, local_response_format
from product_assistant.schemas import LocalPlan
from product_assistant.service import CardService


def plan_for(product):
    facts = prepare_input(product).facts
    return {
        "seo_title": product.name,
        "description_fact_ids": [
            fact.id for fact in facts if fact.source.startswith("specs.")
        ],
        "search_queries": [
            product.name,
            "купить " + product.name,
            product.name + " характеристики",
        ],
    }


def local_settings():
    return Settings(
        backend="local",
        base_url="http://127.0.0.1:8081/v1",
        model="qwen2.5-1.5b-instruct",
        timeout_seconds=300,
    )


def test_local_http_only_on_loopback():
    assert local_settings().backend == "local"
    with pytest.raises(ValueError):
        Settings(backend="local", base_url="http://example.org/v1")


def test_local_renderer_preserves_attribute_value_binding(product):
    prepared = prepare_input(product)
    card = assemble_local_card(
        product, prepared, LocalPlan.model_validate(plan_for(product))
    )
    assert "Оптическое разрешение — 10:1." in card.seo_description
    assert "Разрешение — 0.5 °C." in card.seo_description
    assert "Оптическое разрешение — 0.5" not in card.seo_description
    assert 800 <= len(card.seo_description) <= 1200
    assert validate_card(card, prepared.facts).passed
    assert card.commercial_block.audience == product.target_audience
    assert card.commercial_block.tasks == product.use_cases


def test_local_fact_ids_are_deduplicated(product):
    data = plan_for(product)
    data["description_fact_ids"] = (
        data["description_fact_ids"][:2] * 5 + data["description_fact_ids"]
    )
    card = assemble_local_card(
        product, prepare_input(product), LocalPlan.model_validate(data)
    )
    assert card.seo_description.count("Оптическое разрешение —") == 1


async def test_local_service_uses_real_plan_contract(product):
    data = plan_for(product)
    result = await CardService(local_settings(), FakeProvider([data])).generate(product)
    assert result.metadata.generation_strategy == "grounded_plan"
    assert result.metadata.model_plan.seo_title == product.name
    assert result.metadata.provider == "llama.cpp / grounded plan"
    assert result.validation.passed


async def test_unknown_local_fact_is_not_rendered(product):
    data = plan_for(product)
    data["description_fact_ids"] = ["F999"]
    settings = Settings(
        backend="local", base_url="http://127.0.0.1:8081/v1", max_attempts=1
    )
    with pytest.raises(GenerationError) as caught:
        await CardService(settings, FakeProvider([data])).generate(product)
    assert caught.value.code == "invalid_model_output"


async def test_local_model_cannot_supply_invented_prose(product):
    data = plan_for(product)
    data["seo_description"] = "Оптическое разрешение 0.5 °C, Бизнес-целлюля."
    settings = Settings(
        backend="local", base_url="http://127.0.0.1:8081/v1", max_attempts=1
    )
    with pytest.raises(GenerationError):
        await CardService(settings, FakeProvider([data])).generate(product)


def test_grammar_only_allows_existing_spec_ids(product):
    prepared = prepare_input(product)
    response = local_response_format(local_messages(prepared.facts))
    schema = response["json_schema"]["schema"]
    allowed = schema["properties"]["description_fact_ids"]["items"]["enum"]
    expected = [fact.id for fact in prepared.facts if fact.source.startswith("specs.")]
    assert allowed == expected
    assert "seo_description" not in schema["properties"]


def test_search_intents_cannot_invent_measurement(product):
    data = plan_for(product)
    data["search_queries"][0] = product.name + " 62 мм"
    with pytest.raises(ValueError):
        assemble_local_card(
            product, prepare_input(product), LocalPlan.model_validate(data)
        )


def test_repeated_queries_are_supplemented_with_grounded_intents(product):
    data = plan_for(product)
    data["search_queries"] = [product.name] * 3
    card = assemble_local_card(
        product, prepare_input(product), LocalPlan.model_validate(data)
    )
    assert len(card.search_queries) == 3
    assert len(set(card.search_queries)) == 3
    assert validate_card(card, prepare_input(product).facts).passed


def test_query_boundaries_do_not_form_quantities(product, good_card):
    card = copy.deepcopy(good_card)
    card["search_queries"] = [product.name, "мм и другие единицы", "поиск прибора"]
    from product_assistant.schemas import LLMCard

    report = validate_card(LLMCard.model_validate(card), prepare_input(product).facts)
    assert not any(
        issue.code == "unsupported_quantity" and issue.field == "search_queries"
        for issue in report.issues
    )


def test_api_documentation_has_no_cdn():
    from fastapi.testclient import TestClient

    from product_assistant.app import create_app

    with TestClient(create_app(Settings(api_key="test"), FakeProvider([]))) as client:
        response = client.get("/docs")
        assert response.status_code == 200
        assert "Документация API" in response.text
        assert "cdn.jsdelivr.net" not in response.text
        assert (
            "ProductInput"
            in client.get("/openapi.json").json()["components"]["schemas"]
        )


def test_saved_example_rejects_unknown_slug():
    from fastapi.testclient import TestClient

    from product_assistant.app import create_app

    with TestClient(create_app(Settings(api_key="test"), FakeProvider([]))) as client:
        response = client.get("/api/examples/unknown/result")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "example_not_found"
