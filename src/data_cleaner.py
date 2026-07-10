import pandas as pd


REQUIRED_COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume", "amount")


def clean_daily_bars(data: pd.DataFrame) -> pd.DataFrame:
    """Standardize a daily price panel and remove unusable observations."""
    missing = set(REQUIRED_COLUMNS).difference(data.columns)
    if missing:
        raise ValueError(f"Daily bar data is missing columns: {missing}")

    cleaned = data.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"])
    numeric_columns = [column for column in REQUIRED_COLUMNS if column not in {"date", "symbol"}]
    cleaned[numeric_columns] = cleaned[numeric_columns].apply(pd.to_numeric, errors="coerce")
    cleaned = cleaned.dropna(subset=["date", "symbol", "close"])
    cleaned = cleaned[cleaned["close"] > 0]
    cleaned = cleaned.drop_duplicates(subset=["date", "symbol"], keep="last")
    return cleaned.sort_values(["symbol", "date"]).reset_index(drop=True)
