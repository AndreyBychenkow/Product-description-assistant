"""Generate the two REAL examples. Never substitute mock or hand-written output.

Run from the project root: python -m scripts.generate_examples
"""

import asyncio
import json
import time
from datetime import datetime, timezone

from product_assistant.config import ROOT, Settings
from product_assistant.provider import GenerationError, OpenAICompatibleProvider
from product_assistant.rendering import to_markdown
from product_assistant.schemas import ProductInput
from product_assistant.service import CardService

SLUGS = ("testo-830-t1", "appa-62")


async def main() -> int:
    settings = Settings.from_env()
    if settings.app_mode == "demo":
        print(
            "Деморежим: новые ответы LLM не генерируются. Настройте APP_MODE=llm и API заказчика. Сохраненные примеры доступны в examples/outputs/."
        )
        return 2
    provider = OpenAICompatibleProvider(settings)
    service = CardService(settings, provider)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": settings.provider_name,
        "model": settings.model,
        "response_format": settings.response_format,
        "max_output_tokens": settings.max_output_tokens,
        "mock_used": False,
        "items": [{"id": slug, "status": "not_run"} for slug in SLUGS],
    }
    failed = False
    try:
        for index, slug in enumerate(SLUGS):
            product = ProductInput.model_validate_json(
                (ROOT / "examples/inputs" / f"{slug}.json").read_text(encoding="utf-8")
            )
            try:
                print(
                    f"{slug}: реальный вызов {settings.provider_name}, ожидаем ответ…",
                    flush=True,
                )
                started = time.perf_counter()
                result = await service.generate(product)
                if result.metadata.mode != "llm":
                    report["items"][index] = {"id": slug, "status": "insufficient_data"}
                    failed = True
                    continue
                target = ROOT / "examples/outputs"
                target.mkdir(parents=True, exist_ok=True)
                (target / f"{slug}.json").write_text(
                    json.dumps(
                        result.model_dump(mode="json"), ensure_ascii=False, indent=2
                    )
                    + "\n",
                    encoding="utf-8",
                )
                (target / f"{slug}.md").write_text(
                    to_markdown(result), encoding="utf-8"
                )
                report["items"][index] = {
                    "id": slug,
                    "status": "generated",
                    "draft_status": result.status,
                    "validation_passed": result.validation.passed,
                    "attempts": result.metadata.attempts,
                    "elapsed_seconds": round(time.perf_counter() - started, 2),
                    "usage": result.metadata.usage,
                }
                print(
                    f"{slug}: реальный результат сохранен; проверки пройдены.",
                    flush=True,
                )
            except GenerationError as exc:
                failed = True
                report["items"][index] = {
                    "id": slug,
                    "status": "failed",
                    "error_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
                print(f"{slug}: {exc.message}", flush=True)
                if exc.code in {
                    "api_key_missing",
                    "provider_insufficient_balance",
                    "provider_auth_error",
                    "session_budget_exceeded",
                }:
                    for pending in range(index + 1, len(SLUGS)):
                        report["items"][pending]["status"] = (
                            "blocked_by_provider_access"
                        )
                    break
    finally:
        await provider.close()
        report["all_generated"] = all(
            item["status"] == "generated" for item in report["items"]
        )
        output = ROOT / "reports/live-generation-status.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
