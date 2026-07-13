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


def monthly_rebalance_dates(trading_dates: pd.Series) -> list[pd.Timestamp]:
    """Select the last real trading date in each calendar month."""
    dates = pd.to_datetime(trading_dates, errors="coerce", utc=True)
    dates = dates.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize().dropna()
    if dates.empty:
        raise ValueError("Trading-date series cannot be empty.")
    month_ends = dates.groupby(dates.dt.to_period("M")).max()
    return month_ends.tolist()


def build_index_stock_pool_history(
    snapshots: dict[pd.Timestamp, pd.DataFrame],
    index_code: str,
) -> pd.DataFrame:
    """Combine point-in-time constituent responses into a monthly membership history."""
    if not snapshots:
        raise ValueError("Constituent snapshots cannot be empty.")
    frames = [
        build_index_stock_pool(constituents, index_code, as_of_date)
        for as_of_date, constituents in snapshots.items()
    ]
    history = pd.concat(frames, ignore_index=True)
    return history.sort_values(["as_of_date", "symbol"]).drop_duplicates(
        ["as_of_date", "symbol"], keep="last"
    ).reset_index(drop=True)
