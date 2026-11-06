import math

import pytest
from pydantic import ValidationError

from product_assistant.config import Settings
from product_assistant.grounding import numbers, prepare_input, validate_card
from product_assistant.schemas import LLMCard, ProductInput


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "  ", "specs": {}},
        {"name": "Прибор", "specs": []},
        {"name": "Прибор", "specs": {"Питание": {"value": 9}}},
        {"name": "Прибор", "specs": {"x": math.nan}},
        {"name": "Прибор", "unexpected": "field"},
        {"name": "Прибор", "source_urls": ["javascript:alert(1)"]},
        {"name": "Прибор", "source_urls": ["https://user:secret@example.org/x"]},
    ],
)
def test_rejects_invalid_input(payload):
    with pytest.raises(ValidationError):
        ProductInput.model_validate(payload)


def test_primitive_specs_and_missing_values():
    product = ProductInput(
        name="Прибор", specs={"A": 9, "B": True, "C": "  ", "D": "данных нет"}
    )
    assert product.specs == {"A": "9", "B": "да", "C": None, "D": None}


def test_characteristics_are_copied_exactly(product):
    prepared = prepare_input(product)
    rows = {item.name: item for item in prepared.characteristics}
    for key, value in product.specs.items():
        assert rows[key].value == (value if value is not None else "данных нет")
    assert rows["Степень защиты"].is_missing is True
    assert "specs.Погрешность" in prepared.missing_fields
    assert "specs.Степень защиты" in prepared.missing_fields
    assert all(fact.source != "specs.Погрешность" for fact in prepared.facts)


def test_unknown_expected_fields_are_not_guessed():
    prepared = prepare_input(ProductInput(name="Прибор", expected_specs=["Интерфейс"]))
    assert prepared.characteristics[0].value == "данных нет"
    assert not prepared.sufficient


def test_numeric_normalization():
    assert numbers("0,50; 10; 1000") == numbers("0.5; 10.0; 1000.0")


def test_valid_fixture_passes(product, good_card):
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert report.passed
    assert 800 <= report.description_length <= 1200


def test_unsupported_number_is_rejected(product, good_card):
    good_card["seo_description"] += " Диапазон до 9999 °C."
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(item.code == "unsupported_number" for item in report.issues)


def test_existing_number_with_wrong_unit_is_rejected(product, good_card):
    # 200 is the sourced mass; it must not become a 200 V supply.
    good_card["seo_description"] += " Питание 200 В."
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(item.code == "unsupported_quantity" for item in report.issues)


def test_unknown_reference_is_rejected(product, good_card):
    good_card["evidence"]["seo_title"] = ["F999"]
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(item.code == "unknown_evidence" for item in report.issues)


def test_duplicate_queries_are_rejected(product, good_card):
    good_card["search_queries"][1] = good_card["search_queries"][0]
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(item.code == "duplicate_queries" for item in report.issues)


def test_unprovided_certification_is_rejected(product, good_card):
    good_card["seo_description"] += " Прибор сертифицирован."
    report = validate_card(
        LLMCard.model_validate(good_card), prepare_input(product).facts
    )
    assert any(item.code == "unsupported_claim" for item in report.issues)


def test_key_hidden_in_configuration_repr():
    assert "test-secret" not in repr(Settings(api_key="test-secret"))


@pytest.mark.parametrize("url", ["http://example.org", "https://user:pass@example.org"])
def test_insecure_api_configuration_is_rejected(url):
    with pytest.raises(ValueError):
        Settings(base_url=url)
