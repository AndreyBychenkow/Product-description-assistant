"""Existing model servers and cloud providers through an API-only adapter."""

import asyncio
import json
from dataclasses import dataclass, field

import openai
from openai import AsyncOpenAI

from .config import Settings
from .local_queries import query_candidates
from .schemas import LLMCard, LocalPlan


class GenerationError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


@dataclass
class ProviderReply:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


def local_response_format(messages: list[dict[str, str]]) -> dict:
    """Constrain the local model to a short factual plan, not free-form specs."""
    schema = LocalPlan.model_json_schema()
    try:
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        facts = payload["source_facts"]
        name = next((fact["value"] for fact in facts if fact["source"] == "name"), "")
        schema["properties"]["search_queries"]["items"] = {
            "type": "string",
            "enum": query_candidates(name),
        }
        if name and len(name) <= 70:
            schema["properties"]["seo_title"] = {"type": "string", "enum": [name]}
        ids = [fact["id"] for fact in facts if fact["source"].startswith("specs.")]
        if not ids:
            ids = [fact["id"] for fact in facts]
        schema["properties"]["description_fact_ids"]["items"] = {
            "type": "string",
            "enum": ids,
        }
    except (IndexError, KeyError, ValueError, TypeError):
        pass
    return {
        "type": "json_schema",
        "json_schema": {"name": "product_plan", "strict": True, "schema": schema},
    }


def card_response_format(messages: list[dict[str, str]]) -> dict:
    """Full LLM-written card, constrained shape/limits, not assembled prose."""
    schema = LLMCard.model_json_schema()
    schema["properties"]["seo_title"]["maxLength"] = 70
    schema["properties"]["seo_description"].update(minLength=800, maxLength=1200)
    schema["properties"]["search_queries"].update(minItems=3, maxItems=5)
    schema["properties"]["search_queries"]["items"].update(minLength=1, maxLength=200)
    try:
        facts = json.loads(messages[1]["content"].split("\n", 1)[1])["source_facts"]
        ids = [fact["id"] for fact in facts]
        if ids:
            for field in schema["$defs"]["Evidence"]["properties"].values():
                field["items"] = {"type": "string", "enum": ids}
    except (IndexError, KeyError, ValueError, TypeError):
        pass
    return {
        "type": "json_schema",
        "json_schema": {"name": "product_card", "strict": True, "schema": schema},
    }


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.requests_used = 0
        self._lock = asyncio.Lock()
        self._client: AsyncOpenAI | None = None

    async def complete(self, messages: list[dict[str, str]]) -> ProviderReply:
        if self.settings.app_mode == "demo":
            raise GenerationError(
                503,
                "demo_mode",
                "Это деморежим без LLM. Доступны проверка данных и сохраненные реальные примеры. Для новой генерации задайте APP_MODE=llm и параметры API заказчика в .env.",
            )
        if not self.settings.model:
            raise GenerationError(
                503,
                "llm_not_configured",
                "Не указан LLM_MODEL. Укажите ID модели, доступной на API-сервере заказчика.",
            )
        local = self.settings.backend == "local"
        name = self.settings.provider_name
        if not self.settings.api_key and self.settings.api_key_required:
            raise GenerationError(
                503,
                "api_key_missing",
                f"Не настроен API-ключ {name}. Добавьте LLM_API_KEY в .env или окружение процесса.",
            )
        async with self._lock:
            if self.requests_used >= self.settings.max_api_requests:
                raise GenerationError(
                    429,
                    "session_budget_exceeded",
                    "Достигнут лимит LLM-вызовов этого запуска. Для продолжения перезапустите сервис или измените MAX_API_REQUESTS.",
                )
            self.requests_used += 1
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.api_key or "local-no-paid-api",
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
                max_retries=0,
            )
        extra_body = None
        if local:
            extra_body = {"repeat_penalty": 1.05}
        elif self.settings.is_openrouter:
            extra_body = {"reasoning": {"enabled": False}}
            if self.settings.model.endswith(":free"):
                # Fail closed if a free route has no zero-price endpoint.
                extra_body["provider"] = {"max_price": {"prompt": 0, "completion": 0}}
        elif self.settings.backend == "deepseek":
            extra_body = {"thinking": {"type": "disabled"}}
        try:
            reply = await self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                response_format=local_response_format(messages)
                if local
                else card_response_format(messages)
                if self.settings.response_format == "json_schema"
                else {"type": "json_object"},
                temperature=0.15 if local else 0.2,
                max_tokens=self.settings.max_output_tokens,
                stream=False,
                extra_body=extra_body,
            )
        except openai.APITimeoutError:
            raise GenerationError(
                504,
                "provider_timeout",
                f"{name} не ответил за отведенное время. Повторите запрос позже или проверьте LLM_TIMEOUT_SECONDS.",
            ) from None
        except openai.APIConnectionError:
            text = (
                "API модели недоступен. Проверьте LLM_BASE_URL и запуск сервера модели на стороне заказчика. Приложение само модель не устанавливает."
                if self.settings.backend != "deepseek"
                else "Не удалось установить HTTPS-соединение с DeepSeek."
            )
            raise GenerationError(502, "provider_connection_error", text) from None
        except openai.APIStatusError as exc:
            if exc.status_code in (401, 403):
                raise GenerationError(
                    503,
                    "provider_auth_error",
                    f"{name} отклонил доступ. Проверьте API-ключ, разрешения, регион и настройки провайдера.",
                ) from None
            if exc.status_code == 402:
                raise GenerationError(
                    503,
                    "provider_insufficient_balance",
                    f"{name} вернул HTTP 402: проверьте баланс, лимит ключа и доступную квоту. Автоматической оплаты или переключения на платную модель нет.",
                ) from None
            if exc.status_code == 429:
                raise GenerationError(
                    503,
                    "provider_rate_limit",
                    f"{name} ограничил частоту запросов. Повторите запрос позже.",
                ) from None
            raise GenerationError(
                502,
                "provider_error",
                f"{name} вернул HTTP {exc.status_code}. Проверьте журнал сервера и выбранную модель.",
            ) from None
        except openai.APIError:
            raise GenerationError(
                502,
                "provider_protocol_error",
                f"Не удалось разобрать ответ {name}. Непроверенный текст не использован.",
            ) from None
        if not getattr(reply, "choices", None):
            raise GenerationError(
                502,
                "provider_empty_choices",
                f"{name} вернул ответ без вариантов текста.",
            )
        usage = {}
        if reply.usage:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(reply.usage, key, None)
                if isinstance(value, int):
                    usage[key] = value
        return ProviderReply(
            content=reply.choices[0].message.content or "",
            model=reply.model or self.settings.model,
            usage=usage,
            finish_reason=reply.choices[0].finish_reason or "stop",
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# Compatibility alias for callers of the initial cloud-only prototype.
DeepSeekProvider = OpenAICompatibleProvider
