"""Application settings. Entry points default to a no-network demo.

The application is ONLY an API client: it never installs or starts an LLM.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # Explicit constructors keep legacy API-client defaults. Public entry points
    # use from_env(), whose safe default is APP_MODE=demo / openai_compatible.
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 60.0
    max_attempts: int = 2
    max_api_requests: int = 20
    backend: str = "deepseek"
    app_mode: str = "llm"
    allow_insecure_http: bool = False
    response_format: str = "json_object"
    max_output_tokens: int = 4096

    @property
    def is_openrouter(self) -> bool:
        return urlparse(self.base_url).hostname in {
            "openrouter.ai",
            "eu.openrouter.ai",
            "us.openrouter.ai",
        }

    @property
    def api_key_required(self) -> bool:
        return self.backend == "deepseek" or self.is_openrouter

    @property
    def provider_name(self) -> str:
        if self.is_openrouter:
            return "OpenRouter"
        return {
            "local": "llama.cpp / grounded plan",
            "deepseek": "DeepSeek",
            "openai_compatible": "OpenAI-compatible API",
        }[self.backend]

    @property
    def can_generate(self) -> bool:
        return (
            self.app_mode == "llm"
            and bool(self.model)
            and (not self.api_key_required or bool(self.api_key))
        )

    def __post_init__(self) -> None:
        if self.response_format not in {"json_object", "json_schema"}:
            raise ValueError(
                "LLM_RESPONSE_FORMAT должен быть json_object или json_schema."
            )
        if not 512 <= self.max_output_tokens <= 16000:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS должен быть от 512 до 16000.")
        if self.app_mode not in {"demo", "llm"}:
            raise ValueError("APP_MODE должен быть demo или llm.")
        if self.backend not in {"openai_compatible", "local", "deepseek"}:
            raise ValueError(
                "LLM_PROVIDER должен быть openai_compatible, local или deepseek."
            )
        parsed = urlparse(self.base_url)
        local_http = (
            self.backend in {"local", "openai_compatible"}
            and parsed.scheme == "http"
            and (
                parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                or self.allow_insecure_http
            )
        )
        if (
            (parsed.scheme != "https" and not local_http)
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "LLM_BASE_URL: используйте HTTPS либо локальный HTTP. Для доверенной HTTP-сети явно задайте LLM_ALLOW_INSECURE_HTTP=true. Учетные данные в URL запрещены."
            )
        if not 5 <= self.timeout_seconds <= 600:
            raise ValueError("LLM_TIMEOUT_SECONDS должен быть от 5 до 600.")
        if self.max_attempts not in (1, 2):
            raise ValueError("LLM_MAX_ATTEMPTS должен быть 1 или 2.")
        if self.max_api_requests < 1:
            raise ValueError("MAX_API_REQUESTS должен быть положительным числом.")

    @classmethod
    def from_env(cls) -> "Settings":
        # An inherited empty Windows variable must not hide a saved .env key.
        # A non-empty explicit environment secret still has priority.
        inherited_key = os.environ.get("LLM_API_KEY")
        if inherited_key is not None and not inherited_key.strip():
            os.environ.pop("LLM_API_KEY", None)
        load_dotenv(ROOT / ".env", override=False, encoding="utf-8-sig")
        backend = os.getenv("LLM_PROVIDER", "openai_compatible").strip().lower()
        default_base = (
            "https://api.deepseek.com"
            if backend == "deepseek"
            else "http://127.0.0.1:1234/v1"
        )
        return cls(
            app_mode=os.getenv("APP_MODE", "demo").strip().lower(),
            response_format=os.getenv("LLM_RESPONSE_FORMAT", "json_object")
            .strip()
            .lower(),
            max_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096")),
            backend=backend,
            api_key=(
                os.getenv("LLM_API_KEY")
                or (os.getenv("DEEPSEEK_API_KEY", "") if backend == "deepseek" else "")
            ).strip(),
            base_url=os.getenv("LLM_BASE_URL", default_base).rstrip("/"),
            model=os.getenv(
                "LLM_MODEL", "deepseek-flash" if backend == "deepseek" else ""
            ).strip(),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
            max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "2")),
            max_api_requests=int(os.getenv("MAX_API_REQUESTS", "20")),
            allow_insecure_http=os.getenv("LLM_ALLOW_INSECURE_HTTP", "false")
            .strip()
            .lower()
            in {"true", "1", "yes"},
        )
