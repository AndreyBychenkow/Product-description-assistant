"""Visual/interaction regression checks. No real model requests are made.

Requires the optional Playwright dev tool and a running app.
BROWSER_BASE_URL=http://127.0.0.1:8010 python -m scripts.ui_review
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from product_assistant.config import ROOT


def main():
    base = os.getenv("BROWSER_BASE_URL", "http://127.0.0.1:8010")
    checks = []
    errors = []
    external = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100}, reduced_motion="reduce"
        )
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on(
            "request",
            lambda req: (
                external.append(req.url)
                if urlparse(req.url).netloc not in {"", urlparse(base).netloc}
                else None
            ),
        )
        before = page.request.get(base + "/health").json()["api_requests_used"]
        page.goto(base, wait_until="networkidle")
        page.locator("#savedExample").click()
        page.get_by_text("СОХРАНЕННЫЙ РЕАЛЬНЫЙ ОТВЕТ LLM", exact=True).wait_for()
        page.evaluate("document.fonts.ready")
        assert page.evaluate("document.fonts.check('600 16px Manrope')")
        assert page.evaluate(
            "[...document.fonts].some(f => f.family === 'Manrope' && f.status === 'loaded')"
        )
        assert (
            page.locator(".seo-description").evaluate(
                "e => parseFloat(getComputedStyle(e).fontSize)"
            )
            >= 15.5
        )
        assert (
            page.locator(".spec-table").evaluate(
                "e => parseFloat(getComputedStyle(e).fontSize)"
            )
            >= 13.5
        )
        if not page.locator("#generate").is_disabled():
            assert "gradient" in page.locator("#generate").evaluate(
                "e => getComputedStyle(e).backgroundImage"
            )
        else:
            expect(page.locator("#generate")).to_be_disabled()
        assert "gradient" in page.locator("#download").evaluate(
            "e => getComputedStyle(e).backgroundImage"
        )
        expect(page.locator("#resultOrigin")).to_contain_text(
            "новый вызов LLM не выполнялся"
        )
        checks.append(
            "Bundled Manrope is actually loaded; larger reading sizes and distinct colored CTAs are applied."
        )
        checks.append(
            "Saved answer has its own explicit origin banner, not a fake live-generation label."
        )
        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        page.screenshot(path=str(ROOT / "reports/studio-overview.png"), full_page=False)
        page.screenshot(
            path=str(ROOT / "reports/studio-desktop-full.png"), full_page=True
        )
        expected = page.request.get(base + "/api/examples/testo-830-t1/result").json()
        page.locator('[data-tab="card"]').focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator('[data-tab="markdown"]')).to_have_attribute(
            "aria-selected", "true"
        )
        assert page.locator("#codeView").inner_text() == expected["markdown"]
        page.locator("#copy").click()
        expect(page.locator("#toast")).to_have_text("Скопировано")
        assert page.evaluate("navigator.clipboard.readText()") == expected["markdown"]
        with page.expect_download() as event:
            page.locator("#download").click()
        download = event.value
        assert download.suggested_filename.endswith(".md")
        assert Path(download.path()).read_text(encoding="utf-8") == expected["markdown"]
        checks.append(
            "Keyboard tabs, Markdown clipboard and real .md download preserve the exact server result."
        )
        page.locator('[data-tab="json"]').click()
        with page.expect_download() as event:
            page.locator("#download").click()
        assert (
            json.loads(Path(event.value.path()).read_text(encoding="utf-8"))
            == expected["result"]
        )
        checks.append("JSON download remains an exact, unchanged CardResult.")
        for width in [1440, 1280, 1024, 768, 390, 360, 320]:
            page.set_viewport_size({"width": width, "height": 1000})
            page.goto(base, wait_until="networkidle")
            page.locator("#savedExample").click()
            page.get_by_text("СОХРАНЕННЫЙ РЕАЛЬНЫЙ ОТВЕТ LLM", exact=True).wait_for()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            ), f"Overflow at {width}"
            if width <= 390:
                assert not page.locator("#jsonDetails").evaluate("e=>e.open")
                assert page.locator("#generate").bounding_box()["height"] >= 44
                assert page.locator("#download").bounding_box()["height"] >= 42
            if width == 390:
                page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                page.screenshot(
                    path=str(ROOT / "reports/studio-mobile-overview.png"),
                    full_page=False,
                )
                page.screenshot(
                    path=str(ROOT / "reports/studio-mobile-full.png"), full_page=True
                )
        checks.append(
            "No horizontal overflow at 1440, 1280, 1024, 768, 390, 360 and 320 px; mobile JSON is collapsible."
        )
        page.set_viewport_size({"width": 1440, "height": 1100})
        page.goto(base, wait_until="networkidle")
        page.locator("#savedExample").click()
        page.get_by_text("СОХРАНЕННЫЙ РЕАЛЬНЫЙ ОТВЕТ LLM", exact=True).wait_for()
        value = {
            "name": "Проверка <b>текста</b>",
            "manufacturer": "Тест",
            "specs": {"Поле <img src=x onerror=alert(1)>": "2 В", "Питание": "9 В"},
            "description": "Подтвержденное описание только для проверки пользовательского интерфейса. "
            * 3,
        }
        page.locator("#editor").fill(json.dumps(value, ensure_ascii=False))
        expect(page.locator("#copy")).to_be_disabled()
        expect(page.locator("#savedExample")).to_be_disabled()
        page.locator("#inspect").click()
        page.get_by_text("Сначала факты. Затем текст.", exact=True).wait_for()
        assert (
            "<img src=x onerror=alert(1)>" in page.locator(".spec-table").inner_text()
        )
        assert page.locator("#cardView img").count() == 0
        checks.append(
            "Editing invalidates stale results; inspection renders untrusted text safely, never as HTML."
        )
        fake = {
            "app_mode": "llm",
            "can_generate": False,
            "model": "nvidia/nemotron-3.5-super-vl:free",
            "api_key_required": True,
            "api_key_configured": False,
            "api_requests_used": 0,
            "api_request_budget": 20,
            "last_error": None,
        }
        page.route(
            "**/health",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(fake)
            ),
        )
        page.goto(base, wait_until="networkidle")
        expect(page.locator("#noticeTitle")).to_have_text(
            "Приложение не видит API-ключ"
        )
        expect(page.locator("#noticeText")).to_contain_text("LLM_API_KEY")
        expect(page.locator("#generate")).to_be_disabled()
        checks.append(
            "Simulated missing-key configuration shows the exact non-secret setting instead of a generic message."
        )
        page.unroute("**/health")
        page.goto(base + "/docs", wait_until="networkidle")
        expect(page.locator("h1")).to_have_text("Документация API")
        page.locator("summary").click()
        expect(page.locator("#schema")).to_contain_text("ProductInput")
        assert base in page.locator("#curl").inner_text()
        checks.append(
            "Restyled API docs retain live schemas and use the current server origin in the curl example."
        )
        after = page.request.get(base + "/health").json()["api_requests_used"]
        assert after == before
        browser.close()
    assert not errors, errors
    assert not external, external
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "checks": checks,
        "page_errors": errors,
        "external_browser_requests": external,
        "llm_requests_added": after - before,
        "configuration_ui_uses_explicit_mock_fixture": True,
    }
    (ROOT / "reports/ui-review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
