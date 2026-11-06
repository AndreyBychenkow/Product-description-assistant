"""Input, LLM and public response contracts."""

import math
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(StrictModel):
    name: str | None = Field(default=None, max_length=220)
    manufacturer: str | None = Field(default=None, max_length=160)
    specs: dict[str, str | None] = Field(default_factory=dict, max_length=40)
    description: str | None = Field(default=None, max_length=12000)
    target_audience: str | None = Field(default=None, max_length=1500)
    use_cases: str | None = Field(default=None, max_length=1500)
    expected_specs: list[str] = Field(default_factory=list, max_length=20)
    source_urls: list[str] = Field(default_factory=list, max_length=5)
    source_warnings: list[str] = Field(default_factory=list, max_length=15)

    @field_validator(
        "name", "manufacturer", "description", "target_audience", "use_cases"
    )
    @classmethod
    def empty_text_is_missing(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("specs", mode="before")
    @classmethod
    def normalize_specs(cls, value: object) -> dict[str, str | None]:
        if not isinstance(value, dict):
            raise ValueError(
                "specs должен быть JSON-объектом, а не списком или строкой."
            )
        result: dict[str, str | None] = {}
        seen: set[str] = set()
        missing = {
            "",
            "данных нет",
            "нет данных",
            "не указано",
            "неизвестно",
            "n/a",
            "null",
            "—",
            "-",
        }
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 160:
                raise ValueError(
                    "Название характеристики должно быть непустой строкой до 160 символов."
                )
            key = key.strip()
            if key.casefold() in seen:
                raise ValueError("Названия характеристик не должны дублироваться.")
            seen.add(key.casefold())
            if item is None:
                text = None
            elif isinstance(item, bool):
                text = "да" if item else "нет"
            elif isinstance(item, (str, int, float)):
                if isinstance(item, float) and not math.isfinite(item):
                    raise ValueError("Числа должны быть конечными.")
                text = str(item).strip()
                if len(text) > 700:
                    raise ValueError(
                        "Значение характеристики слишком длинное: максимум 700 символов."
                    )
                if text.casefold() in missing:
                    text = None
            else:
                raise ValueError(
                    "Значения specs должны быть строками, числами, boolean или null."
                )
            result[key] = text
        return result

    @field_validator("expected_specs", "source_warnings")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            item = item.strip()
            if not item or len(item) > 1200:
                raise ValueError(
                    "Элементы списка должны быть непустыми строками до 1200 символов."
                )
            if item.casefold() not in seen:
                result.append(item)
                seen.add(item.casefold())
        return result

    @field_validator("source_urls")
    @classmethod
    def validate_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlparse(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or len(value) > 1500
            ):
                raise ValueError(
                    "source_urls допускает только HTTP(S)-ссылки без учетных данных."
                )
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def reject_empty_product(self) -> "ProductInput":
        if not (
            self.name
            or self.manufacturer
            or self.description
            or any(self.specs.values())
        ):
            raise ValueError("Передайте хотя бы одно содержательное поле товара.")
        return self


class CommercialBlock(StrictModel):
    audience: str = Field(min_length=1, max_length=700)
    tasks: str = Field(min_length=1, max_length=700)


class Evidence(StrictModel):
    seo_title: list[str] = Field(min_length=1, max_length=50)
    seo_description: list[str] = Field(min_length=1, max_length=50)
    search_queries: list[str] = Field(min_length=1, max_length=50)
    commercial_block: list[str] = Field(min_length=1, max_length=50)


class LLMCard(StrictModel):
    seo_title: str = Field(min_length=1, max_length=400)
    seo_description: str = Field(min_length=1, max_length=4000)
    search_queries: list[str] = Field(min_length=1, max_length=10)
    commercial_block: CommercialBlock
    evidence: Evidence

    @field_validator("search_queries")
    @classmethod
    def nonempty_queries(cls, values: list[str]) -> list[str]:
        if any(not x.strip() or len(x) > 200 for x in values):
            raise ValueError(
                "Поисковые запросы должны быть непустыми строками до 200 символов."
            )
        return [x.strip() for x in values]


class Fact(StrictModel):
    id: str
    label: str
    value: str
    source: str


class Characteristic(StrictModel):
    name: str
    value: str
    is_missing: bool = False
    source: str | None = None


class CheckIssue(StrictModel):
    code: str
    field: str
    message: str


class ValidationReport(StrictModel):
    passed: bool
    title_length: int
    description_length: int
    search_query_count: int
    issues: list[CheckIssue] = Field(default_factory=list)


class LocalPlan(StrictModel):
    seo_title: str = Field(min_length=1, max_length=70)
    description_fact_ids: list[str] = Field(min_length=1, max_length=15)

    @field_validator("description_fact_ids", mode="before")
    @classmethod
    def unique_ids(cls, value):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(dict.fromkeys(value))
        return value

    search_queries: list[str] = Field(min_length=3, max_length=5)


class GenerationMetadata(StrictModel):
    provider: str = "DeepSeek"
    generation_strategy: Literal["free_text", "grounded_plan"] = "free_text"
    model_plan: LocalPlan | None = None
    model: str
    mode: Literal["llm", "insufficient_data"]
    generated_at: datetime
    prompt_version: str
    attempts: int
    usage: dict[str, int] = Field(default_factory=dict)
    source_urls: list[str] = Field(default_factory=list)


class CardResult(StrictModel):
    status: Literal["draft", "needs_review", "insufficient_data"]
    product_name: str
    manufacturer: str
    seo_title: str | None
    seo_description: str | None
    characteristics: list[Characteristic]
    search_queries: list[str]
    commercial_block: CommercialBlock | None
    missing_fields: list[str]
    warnings: list[str]
    evidence: Evidence | None
    validation: ValidationReport
    metadata: GenerationMetadata


class GenerationResponse(StrictModel):
    origin: Literal["live", "saved_example"] = "live"
    result: CardResult
    markdown: str
