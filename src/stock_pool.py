from collections.abc import Iterable


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    """Return unique six-digit A-share codes while preserving input order."""
    normalized: list[str] = []
    for symbol in symbols:
        code = str(symbol).strip()
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"Invalid A-share code: {symbol}")
        if code not in normalized:
            normalized.append(code)
    if not normalized:
        raise ValueError("Stock universe cannot be empty.")
    return normalized
