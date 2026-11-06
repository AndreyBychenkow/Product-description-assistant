"""Check the web app without an LLM. Real API call is explicitly opt-in.

python -m scripts.browser_smoke
BROWSER_REAL_GENERATION=1 python -m scripts.browser_smoke  # configured APP_MODE=llm
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from product_assistant.config import ROOT


def main() -> None:
    base = os.getenv("BROWSER_BASE_URL", "http://127.0.0.1:8010")
    real = os.getenv("BROWSER_REAL_GENERATION") == "1"
    errors, checks = [], []
    real_result = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(
            viewport={"width": 1440, "height": 1100}, device_scale_factor=1
        )
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base, wait_until="networkidle")
        health = page.request.get(base + "/health").json()
        demo = health["app_mode"] == "demo"
        stored_testo = page.request.get(
            base + "/api/examples/testo-830-t1/result"
        ).json()["result"]
        stored_appa = page.request.get(base + "/api/examples/appa-62/result").json()[
            "result"
        ]
        if real and demo:
            raise RuntimeError(
                "Для новой генерации сначала задайте APP_MODE=llm и API заказчика. Деморежим не подменяет ответ LLM."
            )
        if demo:
            expect(page.locator("#noticeText")).to_contain_text("ДЕМО БЕЗ LLM")
            expect(page.locator("#generate")).to_be_disabled()
            checks.append(
                "Demo is explicit, generation is disabled, no LLM managed by the app."
            )
        else:
            page.get_by_text("Сначала факты. Затем текст.", exact=True).wait_for()
            page.locator("#savedExample").click()
        page.get_by_text("СОХРАНЕННЫЙ РЕАЛЬНЫЙ ОТВЕТ LLM", exact=True).wait_for()
        expect(page.locator(".seo-title")).to_have_text(stored_testo["seo_title"])
        assert (
            page.locator(".seo-description").inner_text()
            == stored_testo["seo_description"]
        )
        page.screenshot(
            path=str(ROOT / "reports/interface-desktop.png"), full_page=True
        )
        page.locator('[data-tab="json"]').click()
        saved = json.loads(page.locator("#codeView").inner_text())
        assert saved["validation"]["passed"]
        with page.expect_download() as event:
            page.locator("#download").click()
        downloaded = json.loads(Path(event.value.path()).read_text(encoding="utf-8"))
        assert downloaded == saved
        page.locator("#copy").click()
        expect(page.locator("#toast")).to_have_text("Скопировано")
        assert json.loads(page.evaluate("navigator.clipboard.readText()")) == saved
        checks.append("Clipboard JSON is identical to the displayed genuine card.")
        checks.append(
            "Genuine saved testo card is clearly labelled; JSON download has its actual data."
        )
        page.locator('[data-tab="markdown"]').click()
        assert "данных нет" in page.locator("#codeView").inner_text()
        checks.append("Markdown export keeps missing-data labels.")
        page.locator('[data-example="appa-62"]').click()
        expect(page.locator("#editor")).to_have_value(re.compile("Мультиметр APPA 62"))
        page.get_by_text("Сначала факты. Затем текст.", exact=True).wait_for()
        checks.append("Input JSON is inspected without an LLM call.")
        page.locator("#savedExample").click()
        expect(page.locator(".seo-title")).to_have_text(stored_appa["seo_title"])
        page.get_by_text("СОХРАНЕННЫЙ РЕАЛЬНЫЙ ОТВЕТ LLM", exact=True).wait_for()
        data = page.request.get(base + "/api/examples/appa-62/result").json()
        assert data["origin"] == "saved_example"
        checks.append(
            "Second genuine saved card has an explicit saved_example API origin."
        )
        if real:
            started = time.perf_counter()
            with page.expect_response(
                lambda r: (
                    r.url.endswith("/api/generate") and r.request.method == "POST"
                ),
                timeout=600_000,
            ) as event:
                page.locator("#generate").click()
            response = event.value
            assert response.status == 200, response.text()
            response_data = response.json()
            result = response_data["result"]
            assert response_data["origin"] == "live"
            assert (
                result["metadata"]["mode"] == "llm" and result["validation"]["passed"]
            )
            assert (
                result["metadata"]["generated_at"]
                != stored_appa["metadata"]["generated_at"]
            )
            expect(page.locator(".seo-title")).to_have_text(result["seo_title"])
            page.screenshot(
                path=str(ROOT / "reports/interface-live-generation.png"), full_page=True
            )
            (ROOT / "reports/live-browser-card.json").write_text(
                json.dumps(response_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            real_result = {
                "http_status": 200,
                "provider": result["metadata"]["provider"],
                "generated_at": result["metadata"]["generated_at"],
                "generation_strategy": result["metadata"]["generation_strategy"],
                "elapsed_seconds": round(time.perf_counter() - started, 2),
                "model": result["metadata"]["model"],
                "attempts": result["metadata"]["attempts"],
                "validation": result["validation"],
            }
            (ROOT / "reports/live-browser-generation.json").write_text(
                json.dumps(real_result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            checks.append(
                "Explicit opt-in generation reached the configured customer's API."
            )
        elif demo:
            rich = json.loads(page.locator("#editor").input_value())
            response = page.request.post(base + "/api/generate", data=rich)
            assert response.status == 503
            assert response.json()["error"]["code"] == "demo_mode"
            assert "result" not in response.json()
            checks.append(
                "Demo cannot masquerade a saved card as a new generation (503 demo_mode)."
            )
        page.locator("#missingDemo").click()
        page.get_by_text("Нечего выдумывать — нужно уточнить.", exact=True).wait_for()
        sparse = json.loads(page.locator("#editor").input_value())
        response = page.request.post(base + "/api/generate", data=sparse)
        assert response.status == 200
        result = response.json()["result"]
        assert (
            result["status"] == "insufficient_data"
            and result["metadata"]["attempts"] == 0
        )
        checks.append(
            "Missing fields are visible; sparse API input has zero LLM attempts."
        )
        page.locator("#editor").fill("{broken json")
        page.locator("#inspect").click()
        page.get_by_text(
            "Входной JSON содержит синтаксическую ошибку.", exact=False
        ).wait_for()
        checks.append("Malformed JSON has a readable local error.")
        page.locator('[data-example="testo-830-t1"]').click()
        page.get_by_text("Сначала факты. Затем текст.", exact=True).wait_for()
        page.locator("#savedExample").click()
        expect(page.locator(".seo-title")).to_have_text(stored_testo["seo_title"])
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1"
        )
        page.screenshot(path=str(ROOT / "reports/interface-mobile.png"), full_page=True)
        checks.append("390px layout has no horizontal overflow.")
        page.goto(base + "/docs", wait_until="networkidle")
        expect(page.locator("h1")).to_have_text("Документация API")
        page.locator("summary").click()
        expect(page.locator("#schema")).to_contain_text("ProductInput")
        checks.append("API documentation works without an external CDN.")
        final_health = page.request.get(base + "/health").json()
        if demo:
            assert final_health["api_requests_used"] == 0
            checks.append(
                "Entire browser scenario finished with ZERO LLM API requests."
            )
        browser.close()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "app_mode": health["app_mode"],
        "checks": checks,
        "page_errors": errors,
        "real_generation": real_result,
        "llm_api_requests_total": final_health["api_requests_used"],
        "model_downloads_by_app": 0,
        "passed": not errors,
    }
    (ROOT / "reports/browser-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if errors:
        raise RuntimeError("Browser page errors detected")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
