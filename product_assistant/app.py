"""Local API and a dependency-free web form. No database, scraping or deployment."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, Settings
from .grounding import prepare_input
from .provider import GenerationError, OpenAICompatibleProvider
from .rendering import to_markdown
from .schemas import CardResult, GenerationResponse, ProductInput
from .service import CardService

EXAMPLES = {
    "testo-830-t1": "testo-830-t1.json",
    "appa-62": "appa-62.json",
}
MAX_BODY_BYTES = 128 * 1024


def create_app(settings: Settings | None = None, provider: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()
    provider = provider or OpenAICompatibleProvider(settings)
    service = CardService(settings, provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if hasattr(provider, "close"):
            await provider.close()

    app = FastAPI(
        title="ТехРедактор — AI-помощник карточек",
        version="1.4.1",
        docs_url=None,
        redoc_url=None,
        description="Черновики B2B-карточек только по входным фактам. Секреты задаются на сервере, а не через веб-форму.",
        lifespan=lifespan,
    )
    app.mount(
        "/assets",
        StaticFiles(directory=ROOT / "product_assistant/static"),
        name="assets",
    )
    app.state.service = service
    app.state.provider = provider
    app.state.last_error = None

    @app.middleware("http")
    async def body_limit_and_headers(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "input_too_large",
                            "message": "Максимальный размер запроса — 128 КиБ.",
                        }
                    },
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        # No frame blocking: the local UI also works inside a preview iframe.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors *"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        fields = [
            {
                "field": ".".join(map(str, item["loc"])),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in exc.errors()[:15]
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_input",
                    "message": "Некорректный JSON или структура товара. Исправьте указанные поля.",
                    "details": fields,
                }
            },
        )

    @app.exception_handler(GenerationError)
    async def generation_error(request: Request, exc: GenerationError):
        app.state.last_error = {"code": exc.code, "message": exc.message}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        return HTMLResponse(
            (ROOT / "product_assistant/templates/index.html").read_text(
                encoding="utf-8"
            )
        )

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    async def api_docs():
        return HTMLResponse(
            (ROOT / "product_assistant/templates/docs.html").read_text(encoding="utf-8")
        )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "model": settings.model or None,
            "app_mode": settings.app_mode,
            "can_generate": settings.can_generate,
            "llm_managed_by_app": False,
            "provider": settings.provider_name,
            "backend": settings.backend,
            "response_format": settings.response_format,
            "max_output_tokens": settings.max_output_tokens,
            "api_key_required": settings.api_key_required,
            "free_route_only": settings.is_openrouter
            and settings.model.endswith(":free"),
            "api_key_configured": bool(settings.api_key),
            "api_requests_used": getattr(provider, "requests_used", 0),
            "api_request_budget": settings.max_api_requests,
            "last_error": app.state.last_error,
            "saved_api_check": None,
        }

    @app.get("/api/examples")
    async def examples():
        result = []
        for slug, filename in EXAMPLES.items():
            item = ProductInput.model_validate_json(
                (ROOT / "examples/inputs" / filename).read_text(encoding="utf-8")
            )
            result.append(
                {"id": slug, "name": item.name, "manufacturer": item.manufacturer}
            )
        return {"items": result}

    @app.get("/api/examples/{slug}", response_model=ProductInput)
    async def example(slug: str):
        if slug not in EXAMPLES:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "example_not_found",
                        "message": "Пример не найден.",
                    }
                },
            )
        return ProductInput.model_validate_json(
            (ROOT / "examples/inputs" / EXAMPLES[slug]).read_text(encoding="utf-8")
        )

    @app.get("/api/examples/{slug}/result", response_model=GenerationResponse)
    async def saved_result(slug: str):
        if slug not in EXAMPLES:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "example_not_found",
                        "message": "Пример не найден.",
                    }
                },
            )
        path = ROOT / "examples/outputs" / f"{slug}.json"
        if not path.exists():
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "result_not_generated",
                        "message": "Сохраненного результата пока нет. Запустите реальную генерацию.",
                    }
                },
            )
        result = CardResult.model_validate_json(path.read_text(encoding="utf-8"))
        return GenerationResponse(
            origin="saved_example", result=result, markdown=to_markdown(result)
        )

    @app.post("/api/inspect")
    async def inspect(product: ProductInput):
        prepared = prepare_input(product)
        return {
            "sufficient_for_generation": prepared.sufficient,
            "fact_count": len(prepared.facts),
            "facts": [fact.model_dump() for fact in prepared.facts],
            "characteristics": [item.model_dump() for item in prepared.characteristics],
            "missing_fields": prepared.missing_fields,
            "warnings": prepared.warnings,
        }

    @app.post("/api/generate", response_model=GenerationResponse)
    async def generate(product: ProductInput):
        result = await service.generate(product)
        app.state.last_error = None
        return GenerationResponse(result=result, markdown=to_markdown(result))

    return app


app = create_app()
