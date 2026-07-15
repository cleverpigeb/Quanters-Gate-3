# 计算价格与成交额因子。

import numpy as np
import pandas as pd

from quanters_gate.validation import require_columns

REQUIRED_COLUMNS = ("date", "symbol", "close", "amount")


def calculate_price_factors(data: pd.DataFrame) -> pd.DataFrame:
    # 从清洗后的复权日线计算首批价格量因子。
    require_columns(data, REQUIRED_COLUMNS, "因子输入")

    factors = data.copy().sort_values(["symbol", "date"]).reset_index(drop=True)
    grouped = factors.groupby("symbol", sort=False, group_keys=False)
    daily_return = grouped["close"].pct_change(fill_method=None)

    factors["momentum_20d"] = grouped["close"].pct_change(20, fill_method=None)
    factors["reversal_5d"] = -grouped["close"].pct_change(5, fill_method=None)
    factors["volatility_20d"] = (
        daily_return.groupby(factors["symbol"], sort=False)
        .rolling(20, min_periods=20)
        .std()
        .reset_index(level=0, drop=True)
    )
    average_amount = (
        grouped["amount"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    )
    factors["turnover_proxy_20d"] = np.log1p(average_amount)
    return factors
