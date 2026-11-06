"""Interactive, hidden API-key setup. No model downloads and no network calls."""

import argparse
import os
import re
import sys
from getpass import getpass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from dotenv import dotenv_values, set_key

from product_assistant.config import ROOT

PRESET = {
    "LLM_PROVIDER": "openai_compatible",
    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
    "LLM_MODEL": "nvidia/nemotron-3.5-super-vl:free",
    "LLM_RESPONSE_FORMAT": "json_schema",
    "LLM_MAX_OUTPUT_TOKENS": "4096",
    "LLM_TIMEOUT_SECONDS": "180",
    "LLM_MAX_ATTEMPTS": "2",
    "MAX_API_REQUESTS": "20",
    "LLM_ALLOW_INSECURE_HTTP": "false",
}


def save_configuration(
    root: Path,
    *,
    demo: bool = False,
    ask_key: Callable[[str], str] | None = None,
) -> Path:
    """Atomically update only preset fields; preserve comments/unrelated settings."""
    target = root / ".env"
    original = (
        target.read_text(encoding="utf-8-sig")
        if target.exists()
        else "# Local configuration. Do not commit this file.\n"
    )
    current = dotenv_values(target, encoding="utf-8-sig") if target.exists() else {}
    file_key = (current.get("LLM_API_KEY") or "").strip()
    # Demo must not copy an environment-only credential onto disk.
    key = file_key if demo else ((os.getenv("LLM_API_KEY") or "").strip() or file_key)
    if not demo:
        prompt = (
            "OpenRouter API key (hidden; Enter keeps existing key): "
            if key
            else "Paste OpenRouter API key (hidden): "
        )
        entered = (ask_key or getpass)(prompt).strip()
        key = entered or key
        if not re.fullmatch(r"sk-or-v1-[A-Za-z0-9_-]{30,256}", key):
            raise ValueError(
                "Нужен полный ключ OpenRouter, начинающийся с sk-or-v1-, без пробелов. Файл не изменен."
            )
    values = {"APP_MODE": "demo" if demo else "llm", **PRESET, "LLM_API_KEY": key}
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".env.configure-",
            dir=root,
            delete=False,
        ) as handle:
            handle.write(original)
            temporary = Path(handle.name)
        for name, value in values.items():
            set_key(temporary, name, value, quote_mode="never", encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Настроить OpenRouter без ручного редактирования .env. Ключ вводится скрыто; модели не скачиваются."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Сохранить деморежим без запроса ключа. Уже сохраненный ключ не стирается.",
    )
    args = parser.parse_args(argv)
    if not args.demo and not sys.stdin.isatty():
        print(
            "Для скрытого ввода запустите команду в обычном окне терминала. Для просмотра без ключа используйте --demo.",
            file=sys.stderr,
        )
        return 2
    try:
        print(
            "Настройка только .env. Модель не устанавливается; запрос к API не выполняется."
        )
        target = save_configuration(ROOT, demo=args.demo)
        print(f"Готово: {target}")
        print(
            "Режим: демо без новой генерации."
            if args.demo
            else "Режим: новая генерация через API. Ключ сохранен и не отображается."
        )
        if not args.demo:
            inherited = (os.getenv("LLM_API_KEY") or "").strip()
            saved = dotenv_values(target, encoding="utf-8-sig").get("LLM_API_KEY")
            if inherited and inherited != saved:
                print(
                    "В окружении задан другой LLM_API_KEY: он имеет приоритет над файлом. Чтобы использовать .env, выполните в PowerShell: Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue"
                )
            print("Проверка: python -m scripts.check_connection")
        print("Запуск: python run.py --host 127.0.0.1")
        print("Адрес: http://127.0.0.1:8010/")
        return 0
    except (ValueError, EOFError) as exc:
        if isinstance(exc, EOFError):
            print(
                "Ввод завершен. Настройка отменена; ключ не записан.", file=sys.stderr
            )
        else:
            print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nНастройка отменена. Файл не изменен.", file=sys.stderr)
        return 1
    except OSError:
        print(
            "Не удалось сохранить .env. Проверьте права на папку проекта. Значение ключа не выводится.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
