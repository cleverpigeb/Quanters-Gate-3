"""清洗并审计日线行情。"""

import numpy as np
import pandas as pd

from quanters_gate.dates import normalize_trade_dates
from quanters_gate.validation import require_columns

REQUIRED_COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume", "amount")
PRICE_COLUMNS = ("open", "high", "low", "close")
NUMERIC_COLUMNS = (*PRICE_COLUMNS, "volume", "amount", "turnover")


def clean_daily_bars(data: pd.DataFrame) -> pd.DataFrame:
    """清洗日线，同时保留停牌事实和额外的业务字段。"""
    require_columns(data, REQUIRED_COLUMNS, "日线数据")

    cleaned = data.copy()
    cleaned["date"] = normalize_trade_dates(cleaned["date"])
    cleaned["symbol"] = cleaned["symbol"].astype("string").str.strip()
    for column in NUMERIC_COLUMNS:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    numeric_columns = [column for column in NUMERIC_COLUMNS if column in cleaned.columns]
    cleaned[numeric_columns] = cleaned[numeric_columns].replace([np.inf, -np.inf], np.nan)

    cleaned = cleaned.dropna(subset=["date", "symbol", *PRICE_COLUMNS, "volume", "amount"])
    cleaned = cleaned[cleaned["symbol"].str.fullmatch(r"\d{6}", na=False)]
    cleaned = cleaned.drop_duplicates(subset=["date", "symbol"], keep="last")

    valid_prices = (cleaned[list(PRICE_COLUMNS)] > 0).all(axis=1)
    valid_range = (cleaned["high"] >= cleaned[["open", "close", "low"]].max(axis=1)) & (
        cleaned["low"] <= cleaned[["open", "close", "high"]].min(axis=1)
    )
    valid_activity = (cleaned["volume"] >= 0) & (cleaned["amount"] >= 0)
    cleaned = cleaned[valid_prices & valid_range & valid_activity].copy()

    # 零成交可能代表停牌，因此保留记录，并将可交易性显式交给后续模块判断。
    cleaned["is_tradable"] = (cleaned["volume"] > 0) & (cleaned["amount"] > 0)
    return cleaned.sort_values(["symbol", "date"]).reset_index(drop=True)


def build_cleaning_summary(raw_data: pd.DataFrame, cleaned_data: pd.DataFrame) -> pd.DataFrame:
    """生成一行清洗审计摘要。"""
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
