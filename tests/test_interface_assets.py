"""UI assets remain local, licensed and independent of model/API setup."""

from fastapi.testclient import TestClient

from product_assistant.app import create_app
from product_assistant.config import Settings


def test_studio_shell_and_assets_are_served_without_an_api_key():
    with TestClient(create_app(Settings(app_mode="demo"))) as client:
        html = client.get("/").text
        assert "Сильная карточка." in html
        assert "/assets/ui.css" in html and "/assets/ui.js" in html
        assert "реальный ответ локальной LLM" not in html
        css = client.get("/assets/ui.css")
        js = client.get("/assets/ui.js")
        assert css.status_code == js.status_code == 200
        assert "Manrope" in css.text and "linear-gradient" in css.text
        assert "fonts.googleapis.com" not in css.text
        assert "innerHTML" not in js.text
        assert client.get("/health").json()["api_requests_used"] == 0


def test_bundled_font_and_license_are_included():
    with TestClient(create_app(Settings(app_mode="demo"))) as client:
        font = client.get("/assets/manrope-variable.ttf")
        license = client.get("/assets/Manrope-OFL.txt")
        assert font.status_code == license.status_code == 200
        assert len(font.content) > 50_000
        assert "SIL OPEN FONT LICENSE" in license.text
        assert client.get("/assets/..%2fconfig.py").status_code == 404


def test_documentation_uses_the_same_local_style_and_still_exposes_schema():
    with TestClient(create_app(Settings(app_mode="demo"))) as client:
        docs = client.get("/docs")
        assert docs.status_code == 200 and "/assets/ui.css" in docs.text
        assert "Документация API" in docs.text
        assert (
            "ProductInput"
            in client.get("/openapi.json").json()["components"]["schemas"]
        )
