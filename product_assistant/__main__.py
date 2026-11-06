"""API generation or explicit offline viewing of a saved genuine example."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import ROOT, Settings
from .provider import GenerationError, OpenAICompatibleProvider
from .rendering import to_markdown
from .schemas import CardResult, ProductInput
from .service import CardService


async def run(args: argparse.Namespace) -> int:
    provider = None
    try:
        if args.saved_example:
            result = CardResult.model_validate_json(
                (ROOT / "examples/outputs" / f"{args.saved_example}.json").read_text(
                    encoding="utf-8"
                )
            )
            print(
                "СОХРАНЕННЫЙ РЕАЛЬНЫЙ ПРИМЕР. Новый запрос к LLM не выполнялся.",
                file=sys.stderr,
            )
        else:
            product = ProductInput.model_validate_json(
                Path(args.input).read_text(encoding="utf-8-sig")
            )
            settings = Settings.from_env()
            provider = OpenAICompatibleProvider(settings)
            result = await CardService(settings, provider).generate(product)
        text = (
            to_markdown(result)
            if args.format == "markdown"
            else json.dumps(
                result.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
            + "\n"
        )
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            print(f"Результат сохранен: {output}")
        else:
            print(text)
        return 2 if result.status == "insufficient_data" else 0
    except GenerationError as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValidationError, ValueError) as exc:
        message = (
            [
                {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                for item in exc.errors(include_input=False, include_url=False)[:10]
            ]
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        print(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_input_or_configuration",
                        "message": message,
                    }
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if provider:
            await provider.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Карточки через API заказчика; сохраненные примеры доступны без LLM."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input", help="JSON для НОВОЙ генерации через настроенный API."
    )
    source.add_argument(
        "--saved-example",
        choices=("testo-830-t1", "appa-62"),
        help="Прочитать сохраненный реальный результат, без обращения к LLM.",
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", help="Файл результата; по умолчанию stdout.")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
