"""Render the REAL model's plan using only immutable input facts.

The small CPU model chooses title, queries, selection and ordering. It never
writes a technical value or assigns one field's value to another field.
"""

import re

from .grounding import PreparedInput
from .local_queries import query_candidates
from .schemas import CommercialBlock, Evidence, LLMCard, LocalPlan, ProductInput


def sentence(value: str) -> str:
    value = value.strip()
    return value if value.endswith((".", "!", "?")) else value + "."


def introductory_text(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    result = []
    for part in parts:
        candidate = " ".join(result + [part])
        if len(candidate) > limit:
            break
        result.append(part)
    return " ".join(result)


def assemble_local_card(
    product: ProductInput, prepared: PreparedInput, plan: LocalPlan
) -> LLMCard:
    by_id = {fact.id: fact for fact in prepared.facts}
    unknown = set(plan.description_fact_ids) - set(by_id)
    if unknown:
        raise ValueError("План содержит несуществующие ID фактов.")
    by_source = {fact.source: fact.id for fact in prepared.facts}
    description_refs = []
    paragraphs = []
    if product.name:
        paragraphs.append(sentence(product.name))
        description_refs.append(by_source["name"])
    if product.manufacturer:
        paragraphs.append(sentence("Производитель — " + product.manufacturer))
        description_refs.append(by_source["manufacturer"])
    intro = introductory_text(product.description)
    if intro:
        paragraphs.append(sentence(intro))
        description_refs.append(by_source["description"])

    available_specs = [
        fact.id for fact in prepared.facts if fact.source.startswith("specs.")
    ]
    ordered = list(dict.fromkeys(plan.description_fact_ids + available_specs))
    selected = []
    for ref in ordered:
        fact = by_id[ref]
        if not fact.source.startswith("specs."):
            continue
        # Keep the complete label/value pair; do not let the model rename a field.
        fragment = sentence(fact.label + " — " + fact.value)
        candidate = " ".join(paragraphs + [fragment])
        if len(candidate) > 1200:
            continue
        paragraphs.append(fragment)
        description_refs.append(ref)
        selected.append(ref)
        if len(candidate) >= 980:
            break
    description = " ".join(paragraphs)
    if len(description) < 800:
        # Only grounded, supplied commercial context may extend a sparse text.
        for field, prefix in (
            ("use_cases", "Задачи — "),
            ("target_audience", "Кому подходит — "),
        ):
            value = getattr(product, field)
            if value:
                candidate = description + " " + sentence(prefix + value)
                if len(candidate) <= 1200:
                    description = candidate
                    description_refs.append(by_source[field])
                if len(description) >= 800:
                    break
    if not 800 <= len(description) <= 1200:
        raise ValueError(
            "Недостаточно подтвержденного текста для описания 800–1200 символов. Добавьте назначение или характеристики; заполнители не используются."
        )

    audience = (
        product.target_audience
        or "Специалисты, которым требуется прибор для задач, указанных в исходном описании."
    )
    tasks = (
        product.use_cases
        or introductory_text(product.description, 650)
        or "Подтвержденных данных о назначении недостаточно; требуется уточнение."
    )
    commercial_refs = [
        by_source[field]
        for field in ("target_audience", "use_cases")
        if field in by_source
    ]
    if not commercial_refs:
        commercial_refs = [by_source.get("description", prepared.facts[0].id)]
    title_refs = [
        by_source[field] for field in ("name", "manufacturer") if field in by_source
    ]
    if not title_refs:
        title_refs = [prepared.facts[0].id]
    candidates = query_candidates(product.name)
    if set(plan.search_queries) - set(candidates):
        raise ValueError("План содержит поисковый запрос вне подтвержденных шаблонов.")
    queries = list(dict.fromkeys(plan.search_queries))
    for candidate in candidates:
        if len(queries) >= 3:
            break
        if candidate not in queries:
            queries.append(candidate)
    return LLMCard(
        seo_title=product.name
        if product.name and len(product.name) <= 70
        else plan.seo_title,
        seo_description=description,
        search_queries=queries,
        commercial_block=CommercialBlock(audience=audience, tasks=tasks),
        evidence=Evidence(
            seo_title=title_refs,
            seo_description=list(dict.fromkeys(description_refs)),
            search_queries=[fact.id for fact in prepared.facts],
            commercial_block=commercial_refs,
        ),
    )
