import pandas as pd


REQUIRED_COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume", "amount")
PRICE_COLUMNS = ("open", "high", "low", "close")
NUMERIC_COLUMNS = PRICE_COLUMNS + ("volume", "amount", "turnover")


def _normalize_trade_dates(values: pd.Series) -> pd.Series:
    """Normalize provider timestamps to timezone-naive Shanghai trading dates."""
    timestamps = pd.to_datetime(values, errors="coerce", utc=True)
    return timestamps.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()


def clean_daily_bars(data: pd.DataFrame) -> pd.DataFrame:
    """Return a validated daily-bar panel without fabricating missing market data."""
    missing = set(REQUIRED_COLUMNS).difference(data.columns)
    if missing:
        raise ValueError(f"Daily bar data is missing columns: {missing}")

    cleaned = data.copy()
    cleaned["date"] = _normalize_trade_dates(cleaned["date"])
    cleaned["symbol"] = cleaned["symbol"].astype("string").str.strip()
    for column in NUMERIC_COLUMNS:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned = cleaned.dropna(subset=["date", "symbol", *PRICE_COLUMNS, "volume", "amount"])
    cleaned = cleaned[cleaned["symbol"].str.fullmatch(r"\d{6}", na=False)]
    cleaned = cleaned.drop_duplicates(subset=["date", "symbol"], keep="last")

    valid_prices = (cleaned[list(PRICE_COLUMNS)] > 0).all(axis=1)
    valid_range = (
        (cleaned["high"] >= cleaned[["open", "close", "low"]].max(axis=1))
        & (cleaned["low"] <= cleaned[["open", "close", "high"]].min(axis=1))
    )
    valid_activity = (cleaned["volume"] >= 0) & (cleaned["amount"] >= 0)
    cleaned = cleaned[valid_prices & valid_range & valid_activity].copy()

    # A zero-volume bar can represent a suspension, so retain it and expose tradability.
    cleaned["is_tradable"] = (cleaned["volume"] > 0) & (cleaned["amount"] > 0)
    return cleaned.sort_values(["symbol", "date"]).reset_index(drop=True)


def build_cleaning_summary(raw_data: pd.DataFrame, cleaned_data: pd.DataFrame) -> pd.DataFrame:
    """Summarize the cleaning result for audit without storing a second copy of the data."""
    return pd.DataFrame(
        [
            {
                "input_rows": len(raw_data),
                "output_rows": len(cleaned_data),
                "removed_rows": len(raw_data) - len(cleaned_data),
                "symbol_count": cleaned_data["symbol"].nunique(),
                "first_date": cleaned_data["date"].min(),
                "last_date": cleaned_data["date"].max(),
                "untradable_rows": int((~cleaned_data["is_tradable"]).sum()),
            }
        ]
    )
