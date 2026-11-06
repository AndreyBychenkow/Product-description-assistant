"""Copy-friendly Markdown. No generation and no factual transformations here."""

from html import escape

from .schemas import CardResult


def safe(text: str) -> str:
    return (
        escape(text, quote=False)
        .replace("|", "\\|")
        .replace("\r", "")
        .replace("\n", " ")
    )


def to_markdown(result: CardResult) -> str:
    labels = {
        "draft": "Черновик",
        "needs_review": "Требует уточнений",
        "insufficient_data": "Недостаточно данных",
    }
    lines = [
        f"# {safe(result.product_name)}",
        "",
        f"**Производитель:** {safe(result.manufacturer)}",
        f"**Статус:** {labels[result.status]}",
        "",
        "## SEO-заголовок",
        "",
        safe(result.seo_title or "Не сформирован: недостаточно данных."),
        "",
        "## SEO-описание",
        "",
        safe(
            result.seo_description
            or "Не сформировано: добавьте подтвержденные технические сведения."
        ),
        "",
        "## Ключевые характеристики",
        "",
        "| Характеристика | Значение |",
        "| --- | --- |",
    ]
    for item in result.characteristics:
        lines.append(f"| {safe(item.name)} | {safe(item.value)} |")
    lines += ["", "## Поисковые запросы", ""]
    lines += [f"- {safe(query)}" for query in result.search_queries] or [
        "Не сформированы."
    ]
    lines += ["", "## Для менеджера", ""]
    if result.commercial_block:
        lines += [
            f"**Кому подходит:** {safe(result.commercial_block.audience)}",
            "",
            f"**Задачи:** {safe(result.commercial_block.tasks)}",
        ]
    else:
        lines.append("Недостаточно данных о назначении и функциях.")
    if result.missing_fields:
        lines += ["", "## Что уточнить", ""] + [
            f"- {safe(field)} — данных нет." for field in result.missing_fields
        ]
    lines += ["", "## Примечания редактору", ""] + [
        f"- {safe(warning)}" for warning in result.warnings
    ]
    lines += [
        "",
        "## Автоматическая проверка",
        "",
        f"- Заголовок: {result.validation.title_length}/70 символов.",
        f"- Описание: {result.validation.description_length}/800–1200 символов.",
        f"- Поисковые запросы: {result.validation.search_query_count}/3–5.",
        f"- Проверки: {'пройдены' if result.validation.passed else 'не пройдены'}.",
    ]
    if result.metadata.source_urls:
        lines += ["", "## Источники входных данных", ""] + [
            f"- <{url}>" for url in result.metadata.source_urls
        ]
    lines += [
        "",
        f"Модель: {safe(result.metadata.model)}. Версия промпта: {result.metadata.prompt_version}. Попыток: {result.metadata.attempts}.",
        "",
    ]
    return "\n".join(lines)
