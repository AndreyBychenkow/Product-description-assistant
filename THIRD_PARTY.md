# Сторонние компоненты

- Python-библиотеки перечислены в `requirements.txt` / `requirements-dev.txt`; лицензии — у авторов пакетов.
- Manrope Variable взят из [официального Google Fonts](https://github.com/google/fonts/tree/main/ofl/manrope). SIL Open Font License включена: `product_assistant/static/Manrope-OFL.txt`. Шрифт поставляется локально, без внешнего CDN и установки в систему.
- Проверенный LLM API: [OpenRouter / NVIDIA Nemotron 3.5 Super VL Free](https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free). Использование подчиняется условиям провайдера, включая квоты и обработку данных. В примерах передавались публичные товарные сведения.
- Входы подготовлены по страницам souz-pribor.ru для тестового задания. Выдержки/атрибуция — `examples/sources/`.

Модельные веса и движки не включены и приложением не загружаются. Для другого API/модели владелец проверяет условия использования самостоятельно.
