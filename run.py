"""Start ONLY the web application; never download or start an LLM."""

import argparse
import os

import uvicorn


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ТехРедактор: приложение без загрузки LLM. По умолчанию безопасный деморежим."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--mode", choices=("demo", "llm"), help="Переопределить APP_MODE из .env."
    )
    args = parser.parse_args(argv)
    if args.mode:
        os.environ["APP_MODE"] = args.mode
    print(
        "Запускается только веб-приложение. Модели не скачиваются и не запускаются. Настройки существующего API — в .env.",
        flush=True,
    )
    uvicorn.run(
        "product_assistant.app:app", host=args.host, port=args.port, use_colors=False
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
