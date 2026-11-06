"""Deterministic characteristics and conservative, non-semantic output checks."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from .schemas import (
    Characteristic,
    CheckIssue,
    Fact,
    LLMCard,
    ProductInput,
    ValidationReport,
)


@dataclass
class PreparedInput:
    facts: list[Fact]
    characteristics: list[Characteristic]
    missing_fields: list[str]
    warnings: list[str]
    sufficient: bool


def prepare_input(product: ProductInput) -> PreparedInput:
    facts: list[Fact] = []
    characteristics: list[Characteristic] = []
    missing: list[str] = []

    def add_fact(label: str, value: str, source: str) -> None:
        facts.append(
            Fact(id=f"F{len(facts) + 1:03d}", label=label, value=value, source=source)
        )

    for field, label in (("name", "Название"), ("manufacturer", "Производитель")):
        value = getattr(product, field)
        if value:
            add_fact(label, value, field)
        else:
            missing.append(field)

    present_keys = {key.casefold() for key in product.specs}
    specs = dict(product.specs)
    for key in product.expected_specs:
        if key.casefold() not in present_keys:
            specs[key] = None
            present_keys.add(key.casefold())
    for key, value in specs.items():
        source = f"specs.{key}"
        characteristics.append(
            Characteristic(
                name=key,
                value=value or "данных нет",
                is_missing=value is None,
                source=source if value is not None else None,
            )
        )
        if value is None:
            missing.append(source)
        else:
            add_fact(key, value, source)
    if not characteristics:
        characteristics.append(
            Characteristic(
                name="Технические характеристики", value="данных нет", is_missing=True
            )
        )
        missing.append("specs")
    if product.description:
        add_fact("Описание и назначение", product.description, "description")
    else:
        missing.append("description")
    for field, label in (("target_audience", "Кому подходит"), ("use_cases", "Задачи")):
        value = getattr(product, field)
        if value:
            add_fact(label, value, field)
    warnings = list(product.source_warnings)
    if missing:
        warnings.append(
            "Отсутствующие поля не восстанавливались по памяти модели; уточните их перед публикацией."
        )
    sufficient = (
        sum(value is not None for value in product.specs.values()) >= 2
        or len(product.description or "") >= 120
    )
    return PreparedInput(
        facts, characteristics, list(dict.fromkeys(missing)), warnings, sufficient
    )


def canonical(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    text = text.replace("−", "-").replace("–", "-").replace("…", "...")
    text = text.replace("°с", "°c").replace("х", "x").replace("×", "x")
    return re.sub(r"\s+", " ", text)


def numbers(text: str) -> set[str]:
    return {
        str(Decimal(item).normalize())
        for item in re.findall(r"\d+(?:\.\d+)?", canonical(text))
    }


# Units are deliberately not converted. The guard is conservative: unsupported
# unit/value pairs are rejected even when a conversion could be mathematically valid.
UNIT_PATTERN = r"(?:мкф|мкв|мка|мпа|кпа|мом|ком|мв|ма|мгц|кгц|пф|нф|мф|мм|кг|мс|°c|гц|ом|в|а|г|ч|%|mv|ma|kv|hz|mm|kg|ohm|v|a|g|h)"
QUANTITY_RE = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*(" + UNIT_PATTERN + r")(?![a-zа-яё])", re.IGNORECASE
)


def quantities(text: str) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for value, unit in QUANTITY_RE.findall(canonical(text)):
        result.add((str(Decimal(value).normalize()), unit))
    return result


# These are risk indicators, not a complete semantic factuality proof.
RISK_ROOTS = (
    "сертифиц",
    "взрывозащи",
    "водонепроница",
    "ударопроч",
    "гаранти",
    "доставк",
    "поверк",
    "гост",
    "atex",
    "в наличии",
)


def validate_card(card: LLMCard, facts: list[Fact]) -> ValidationReport:
    issues: list[CheckIssue] = []

    def add(code: str, field: str, message: str) -> None:
        issues.append(CheckIssue(code=code, field=field, message=message))

    title_length = len(card.seo_title)
    description_length = len(card.seo_description)
    if title_length > 70:
        add(
            "title_length",
            "seo_title",
            f"Заголовок: {title_length} символов; максимум 70 с пробелами.",
        )
    if not 800 <= description_length <= 1200:
        add(
            "description_length",
            "seo_description",
            f"Описание: {description_length} символов; необходимо 800–1200 с пробелами.",
        )
    if not 3 <= len(card.search_queries) <= 5:
        add("query_count", "search_queries", "Необходимо от 3 до 5 поисковых запросов.")
    if len({x.casefold() for x in card.search_queries}) != len(card.search_queries):
        add(
            "duplicate_queries",
            "search_queries",
            "Поисковые запросы должны различаться.",
        )

    # A length-constrained decoder can cut a unit off a trailing measurement.
    # Model/article numbers in the original product name are legitimate suffixes.
    tail = re.search(r"[+-]?\d+(?:\.\d+)?$", canonical(card.seo_title))
    identity_numbers = set().union(
        *(numbers(fact.value) for fact in facts if fact.source == "name")
    )
    if tail and numbers(tail.group(0)) - identity_numbers:
        add(
            "unqualified_title_number",
            "seo_title",
            "Заголовок заканчивается числом параметра без единицы/пояснения. Сократи заголовок до названия и категории либо укажи параметр полностью; не обрывай единицу ради длины.",
        )

    if re.search(r"\d\s*°$", canonical(card.seo_title)):
        add(
            "incomplete_title_unit",
            "seo_title",
            "В конце заголовка оборвано обозначение температуры: после ° нужна шкала. Убери диапазон из короткого заголовка либо укажи единицу полностью.",
        )

    by_id = {fact.id: fact for fact in facts}
    sections = {
        "seo_title": [card.seo_title],
        "seo_description": [card.seo_description],
        "search_queries": card.search_queries,
        "commercial_block": [
            card.commercial_block.audience,
            card.commercial_block.tasks,
        ],
    }
    for field, fragments in sections.items():
        text = "\n".join(fragments)
        references = getattr(card.evidence, field)
        unknown = sorted(set(references) - set(by_id))
        if unknown:
            add(
                "unknown_evidence",
                field,
                "Несуществующие ID фактов: " + ", ".join(unknown),
            )
        source_fragments = [
            by_id[ref].label + ": " + by_id[ref].value
            for ref in references
            if ref in by_id
        ]
        source = "\n".join(source_fragments)
        extra_numbers = numbers(text) - numbers(source)
        if extra_numbers:
            add(
                "unsupported_number",
                field,
                "Числа отсутствуют в указанных фактах: "
                + ", ".join(sorted(extra_numbers)),
            )
        # Do not invent a value/unit pair across two different queries or facts.
        output_quantities = set().union(*(quantities(item) for item in fragments))
        source_quantities = set().union(
            *(quantities(item) for item in source_fragments)
        )
        extra_quantities = output_quantities - source_quantities
        if extra_quantities:
            add(
                "unsupported_quantity",
                field,
                "Сочетания значения и единицы не подтверждены: "
                + ", ".join(
                    f"{value} {unit}" for value, unit in sorted(extra_quantities)
                ),
            )
        for root in RISK_ROOTS:
            if root in canonical(text) and root not in canonical(source):
                add(
                    "unsupported_claim",
                    field,
                    f"Утверждение со словом «{root}» не подтверждено указанными фактами.",
                )
        for protection in re.findall(r"\bip\s*\d{2,3}\b", canonical(text)):
            if protection.replace(" ", "") not in canonical(source).replace(" ", ""):
                add(
                    "unsupported_protection",
                    field,
                    "Степень защиты не подтверждена исходными фактами.",
                )
    return ValidationReport(
        passed=not issues,
        title_length=title_length,
        description_length=description_length,
        search_query_count=len(card.search_queries),
        issues=issues,
    )
