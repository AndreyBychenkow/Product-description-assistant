"""Conservative search intents; a price query is not a claim about a price."""


def query_candidates(name: str | None) -> list[str]:
    base = (name or "измерительный прибор").strip()
    if len(base) > 140:
        prefix = base[:140]
        base = prefix.rsplit(" ", 1)[0] if " " in prefix else prefix
    return [
        base,
        "купить " + base,
        base + " характеристики",
        base + " цена",
        base + " описание",
        base + " технические характеристики",
    ]
