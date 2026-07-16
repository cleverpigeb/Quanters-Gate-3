# 计算价格与成交额因子。

import numpy as np
import pandas as pd

from quanters_gate.data.dates import normalize_trade_dates_with_positions
from quanters_gate.data.universe import normalize_symbol_values
from quanters_gate.validation import require_columns, require_unique_rows

REQUIRED_COLUMNS = ("date", "symbol", "close", "amount")
PRICE_FACTOR_COLUMNS = (
    "momentum_20d",
    "reversal_5d",
    "volatility_20d",
    "turnover_proxy_20d",
)


def calculate_price_factors(data: pd.DataFrame) -> pd.DataFrame:
    # 从清洗后的复权日线计算首批价格量因子。
    require_columns(data, REQUIRED_COLUMNS, "因子输入")

    factors = data.copy()
    factors["date"], factors["_trade_date_position"] = normalize_trade_dates_with_positions(
        factors["date"],
        "因子输入",
    )
    factors["symbol"] = normalize_symbol_values(factors["symbol"], "因子输入")
    factors = factors.sort_values(["symbol", "date"]).reset_index(drop=True)
    require_unique_rows(factors, ("date", "symbol"), "因子输入")
    grouped = factors.groupby("symbol", sort=False, group_keys=False)
    position = factors["_trade_date_position"]
    daily_return = grouped["close"].pct_change(fill_method=None)
    daily_return = daily_return.where(grouped["_trade_date_position"].diff().eq(1))

    momentum_span = position - grouped["_trade_date_position"].shift(20)
    reversal_span = position - grouped["_trade_date_position"].shift(5)
    factors["momentum_20d"] = (
        grouped["close"].pct_change(20, fill_method=None).where(momentum_span.eq(20))
    )
    factors["reversal_5d"] = (
        -grouped["close"].pct_change(5, fill_method=None).where(reversal_span.eq(5))
    )
    factors["volatility_20d"] = (
        daily_return.groupby(factors["symbol"], sort=False)
        .rolling(20, min_periods=20)
        .std()
        .reset_index(level=0, drop=True)
    )
    average_amount = (
        grouped["amount"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    )
    amount_span = position - grouped["_trade_date_position"].shift(19)
    factors["turnover_proxy_20d"] = np.log1p(average_amount.where(amount_span.eq(19)))
    return factors.drop(columns="_trade_date_position")
