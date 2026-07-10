import numpy as np
import pandas as pd


def calculate_price_factors(data: pd.DataFrame) -> pd.DataFrame:
    """Calculate a small, interpretable first set of daily price-volume factors."""
    factors = data.copy().sort_values(["symbol", "date"])
    grouped = factors.groupby("symbol", group_keys=False)
    daily_return = grouped["close"].pct_change()

    factors["momentum_20d"] = grouped["close"].pct_change(20)
    factors["reversal_5d"] = -grouped["close"].pct_change(5)
    factors["volatility_20d"] = daily_return.groupby(factors["symbol"]).transform(
        lambda series: series.rolling(20, min_periods=15).std()
    )
    factors["turnover_proxy_20d"] = grouped["amount"].transform(
        lambda series: np.log1p(series.rolling(20, min_periods=15).mean())
    )
    return factors
