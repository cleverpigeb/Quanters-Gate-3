from collections.abc import Iterable

import pandas as pd


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


def build_index_stock_pool(
    constituents: pd.DataFrame,
    index_code: str,
    as_of_date: str,
) -> pd.DataFrame:
    """Build an auditable stock-pool snapshot from one index constituent response."""
    required_columns = {"symbol", "name", "market", "area_code"}
    missing = required_columns.difference(constituents.columns)
    if missing:
        raise ValueError(f"Constituent data is missing columns: {missing}")

    pool = constituents.copy()
    pool["symbol"] = normalize_symbols(pool["symbol"])
    pool["index_code"] = index_code
    pool["as_of_date"] = pd.Timestamp(as_of_date).normalize()
    pool = pool[["as_of_date", "index_code", "symbol", "name", "market", "area_code"]]
    return pool.sort_values("symbol").drop_duplicates("symbol").reset_index(drop=True)
