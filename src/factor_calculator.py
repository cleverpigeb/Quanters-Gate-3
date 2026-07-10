import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("date", "symbol", "close", "amount")


def calculate_price_factors(data: pd.DataFrame) -> pd.DataFrame:
    """Calculate the first price-volume factors from cleaned, adjusted daily bars."""
    missing = set(REQUIRED_COLUMNS).difference(data.columns)
    if missing:
        raise ValueError(f"Factor input is missing columns: {missing}")

    factors = data.copy().sort_values(["symbol", "date"])
    grouped = factors.groupby("symbol", group_keys=False)
    daily_return = grouped["close"].pct_change(fill_method=None)

    factors["momentum_20d"] = grouped["close"].pct_change(20, fill_method=None)
    factors["reversal_5d"] = -grouped["close"].pct_change(5, fill_method=None)
    factors["volatility_20d"] = daily_return.groupby(factors["symbol"]).transform(
        lambda series: series.rolling(20, min_periods=20).std()
    )
    factors["turnover_proxy_20d"] = grouped["amount"].transform(
        lambda series: np.log1p(series.rolling(20, min_periods=20).mean())
    )
    return factors
