"""Orchestrate preflight, one model and at most one output correction."""

from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from .config import Settings
from .grounding import prepare_input, validate_card
from .local_rendering import assemble_local_card
from .prompts import (
    PROMPT_VERSION,
    correction_message,
    initial_messages,
    local_messages,
)
from .provider import GenerationError, ProviderReply
from .schemas import (
    CardResult,
    CheckIssue,
    GenerationMetadata,
    LLMCard,
    LocalPlan,
    ProductInput,
    ValidationReport,
)


class Provider(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> ProviderReply: ...


class CardService:
    def __init__(self, settings: Settings, provider: Provider):
        self.settings = settings
        self.provider = provider

    async def generate(self, product: ProductInput) -> CardResult:
        prepared = prepare_input(product)
        common = {
            "product_name": product.name or "данных нет",
            "manufacturer": product.manufacturer or "данных нет",
            "characteristics": prepared.characteristics,
            "missing_fields": prepared.missing_fields,
        }
        if not prepared.sufficient:
            return CardResult(
                **common,
                status="insufficient_data",
                seo_title=None,
                seo_description=None,
                search_queries=[],
                commercial_block=None,
                evidence=None,
                warnings=prepared.warnings
                + [
                    "Недостаточно фактов для содержательного описания 800–1200 символов. Добавьте характеристики или описание назначения. API не вызывался."
                ],
                validation=ValidationReport(
                    passed=False,
                    title_length=0,
                    description_length=0,
                    search_query_count=0,
                    issues=[
                        CheckIssue(
                            code="insufficient_data",
                            field="input",
                            message="Нужны как минимум две заполненные характеристики или описание от 120 символов. Это эвристика MVP, не оценка полноты паспорта.",
                        )
                    ],
                ),
                metadata=GenerationMetadata(
                    provider=self.settings.provider_name,
                    model=self.settings.model,
                    mode="insufficient_data",
                    generated_at=datetime.now(timezone.utc),
                    prompt_version=PROMPT_VERSION,
                    attempts=0,
                    source_urls=product.source_urls,
                ),
            )

        local = self.settings.backend == "local"
        messages = (
            local_messages(prepared.facts)
            if local
            else initial_messages(prepared.facts)
        )
        usage: dict[str, int] = {}
        last_issues: list[CheckIssue] = []
        for attempt in range(1, self.settings.max_attempts + 1):
            reply = await self.provider.complete(messages)
            for key, value in reply.usage.items():
                usage[key] = usage.get(key, 0) + value
            card: LLMCard | None = None
            title_adjusted = False
            plan: LocalPlan | None = None
            if not reply.content.strip():
                last_issues = [
                    CheckIssue(
                        code="empty_response",
                        field="response",
                        message="Пустой ответ модели. Верни JSON-объект с заполненными полями.",
                    )
                ]
            elif reply.finish_reason != "stop":
                last_issues = [
                    CheckIssue(
                        code="incomplete_response",
                        field="response",
                        message="Ответ не завершен штатно. Верни компактный полный JSON в рамках ограничений.",
                    )
                ]
            else:
                try:
                    if local:
                        plan = LocalPlan.model_validate_json(reply.content)
                        card = assemble_local_card(product, prepared, plan)
                    else:
                        card = LLMCard.model_validate_json(reply.content)
                    validation = validate_card(card, prepared.facts)
                    # A decoder may clip a temperature unit at its title limit.
                    # Prefer an explicit, source-only short identity to an
                    # ambiguous measurement; never invent a missing unit.
                    title_fault = any(
                        issue.code
                        in {"unqualified_title_number", "incomplete_title_unit"}
                        for issue in validation.issues
                    )
                    if title_fault and product.name and len(product.name) <= 70:
                        name_id = next(
                            fact.id for fact in prepared.facts if fact.source == "name"
                        )
                        card = card.model_copy(
                            update={
                                "seo_title": product.name,
                                "evidence": card.evidence.model_copy(
                                    update={"seo_title": [name_id]}
                                ),
                            }
                        )
                        title_adjusted = True
                        validation = validate_card(card, prepared.facts)
                    last_issues = validation.issues
                except ValidationError as exc:
                    last_issues = [
                        CheckIssue(
                            code="response_schema",
                            field="response",
                            message="; ".join(
                                ".".join(map(str, item["loc"])) + ": " + item["msg"]
                                for item in exc.errors(
                                    include_input=False, include_url=False
                                )[:6]
                            ),
                        )
                    ]
                except ValueError as exc:
                    last_issues = [
                        CheckIssue(
                            code="grounded_assembly",
                            field="seo_description",
                            message=str(exc),
                        )
                    ]
            if card is not None and not last_issues:
                warnings = prepared.warnings + [
                    "Это черновик: автоматические проверки чисел, единиц и ссылок на факты не заменяют проверку смысла техническим специалистом."
                ]
                if title_adjusted:
                    warnings.append(
                        "Заголовок модели содержал оборванный числовой параметр/единицу. Вместо него использовано короткое исходное название товара; значение параметра не угадывалось."
                    )
                if attempt > 1:
                    warnings.append(
                        "Модель исправила ответ после автоматической проверки."
                    )
                return CardResult(
                    **common,
                    status="needs_review"
                    if prepared.missing_fields or product.source_warnings
                    else "draft",
                    seo_title=card.seo_title,
                    seo_description=card.seo_description,
                    search_queries=card.search_queries,
                    commercial_block=card.commercial_block,
                    evidence=card.evidence,
                    warnings=warnings,
                    validation=validation,
                    metadata=GenerationMetadata(
                        provider=self.settings.provider_name,
                        generation_strategy="grounded_plan" if local else "free_text",
                        model_plan=plan,
                        model=reply.model,
                        mode="llm",
                        generated_at=datetime.now(timezone.utc),
                        prompt_version=PROMPT_VERSION,
                        attempts=attempt,
                        usage=usage,
                        source_urls=product.source_urls,
                    ),
                )
            if attempt < self.settings.max_attempts:
                # Never feed an incomplete/truncated assistant message back: it
                # can induce continuation loops instead of a fresh valid object.
                if reply.content.strip() and reply.finish_reason == "stop":
                    messages.append({"role": "assistant", "content": reply.content})
                messages.append(
                    correction_message([item.model_dump() for item in last_issues])
                )
        raise GenerationError(
            502,
            "invalid_model_output",
            "Ответ модели не прошел проверку после ограниченного числа попыток. Непроверенный текст не выдан как карточка; уточните данные или повторите запрос позже.",
            [item.model_dump() for item in last_issues],
        )
