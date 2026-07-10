from datetime import date

import akshare as ak
import pandas as pd


def fetch_daily_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch backward-adjusted daily A-share bars from Eastmoney via AkShare."""
    start = pd.Timestamp(start_date).strftime("%Y%m%d")
    end = pd.Timestamp(end_date).strftime("%Y%m%d")
    data = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start,
        end_date=end,
        adjust="hfq",
    )
    if data is None or data.empty:
        raise ValueError(f"No daily bars returned for {symbol}.")

    column_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    missing_columns = set(column_map).difference(data.columns)
    if missing_columns:
        raise ValueError(f"Unexpected data columns for {symbol}: missing {missing_columns}")

    result = data.rename(columns=column_map)[list(column_map.values())].copy()
    result["symbol"] = symbol
    return result


def fetch_universe_daily_bars(
    symbols: list[str], start_date: str, end_date: str
) -> pd.DataFrame:
    """Fetch one panel of daily bars. Failures are reported without losing usable names."""
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for symbol in symbols:
        try:
            frames.append(fetch_daily_bars(symbol, start_date, end_date))
        except Exception as error:  # Data providers can be intermittently unavailable.
            failures.append(f"{symbol}: {error}")

    if not frames:
        raise RuntimeError("No stock data could be fetched. " + "; ".join(failures))
    if failures:
        print("Skipped symbols: " + "; ".join(failures))
    return pd.concat(frames, ignore_index=True)
