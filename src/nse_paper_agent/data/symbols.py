from __future__ import annotations


def canonical_symbol(symbol: str) -> str:
    """Return a stable comparison form for exchange-qualified symbols."""
    value = symbol.strip().upper()
    if ":" in value:
        value = value.split(":", 1)[1]
    if value.endswith("-INDEX"):
        value = value[:-6]
    return value


def resolve_benchmark_symbol(configured: str, available: set[str]) -> str | None:
    """Resolve a configured benchmark name against provider-specific symbols."""
    if configured in available:
        return configured

    configured_canonical = canonical_symbol(configured)
    exact_canonical = [
        symbol for symbol in available
        if canonical_symbol(symbol) == configured_canonical
    ]
    if exact_canonical:
        return sorted(exact_canonical)[0]

    return None
