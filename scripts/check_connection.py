"""One real, tiny JSON API check; no weights, no model management.

python -m scripts.check_connection
"""

import asyncio
import json
import sys
from dataclasses import replace

from product_assistant.config import Settings
from product_assistant.provider import GenerationError, OpenAICompatibleProvider


async def check() -> int:
    provider = None
    try:
        settings = Settings.from_env()
        if settings.app_mode == "demo":
            print(
                "APP_MODE=demo: модель не вызывалась. Для реальной проверки заполните .env и задайте APP_MODE=llm."
            )
            return 2
        provider = OpenAICompatibleProvider(
            replace(settings, response_format="json_object")
        )
        reply = await provider.complete(
            [
                {
                    "role": "system",
                    "content": 'Return only this JSON object: {"status":"ok"}.',
                },
                {"role": "user", "content": "Check the connection."},
            ]
        )
        try:
            payload = json.loads(reply.content)
        except ValueError:
            payload = None
        if payload != {"status": "ok"} or reply.finish_reason != "stop":
            print(
                json.dumps(
                    {
                        "ok": False,
                        "code": "unexpected_check_response",
                        "message": "API ответил, но проверочный JSON не подтвержден. Секреты и сырой ответ не печатаются.",
                    },
                    ensure_ascii=False,
                )
            )
            return 1
        print(
            json.dumps(
                {
                    "ok": True,
                    "provider": settings.provider_name,
                    "model_requested": settings.model,
                    "model_returned": reply.model,
                    "usage": reply.usage,
                    "model_downloaded": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except GenerationError as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code, "message": exc.message},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except ValueError:
        print(
            "Некорректная конфигурация .env. Проверьте имена и формат параметров; секретные значения не печатаются.",
            file=sys.stderr,
        )
        return 1
    finally:
        if provider:
            await provider.close()


def main() -> int:
    return asyncio.run(check())


if __name__ == "__main__":
    raise SystemExit(main())
