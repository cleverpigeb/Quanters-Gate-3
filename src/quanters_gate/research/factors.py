# 计算价格与成交额因子。

import numpy as np
import pandas as pd

from quanters_gate.data.dates import normalize_trade_dates_with_positions
from quanters_gate.data.universe import normalize_symbol_values
from quanters_gate.validation import require_columns, require_unique_rows

REQUIRED_COLUMNS = ("date", "symbol", "close", "amount", "turnover")
PRICE_FACTOR_COLUMNS = (
    "momentum_20d",
    "momentum_60d",
    "reversal_5d",
    "volatility_20d",
    "turnover_proxy_20d",
    "amihud_20d",
    "turnover_surprise_5d_20d",
    "max_return_20d",
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
    medium_momentum_span = position - grouped["_trade_date_position"].shift(60)
    reversal_span = position - grouped["_trade_date_position"].shift(5)
    factors["momentum_20d"] = (
        grouped["close"].pct_change(20, fill_method=None).where(momentum_span.eq(20))
    )
    factors["momentum_60d"] = (
        grouped["close"].pct_change(60, fill_method=None).where(medium_momentum_span.eq(60))
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
    amihud = (daily_return.abs() / factors["amount"]).replace([np.inf, -np.inf], np.nan)
    factors["amihud_20d"] = (
        amihud.groupby(factors["symbol"], sort=False)
        .rolling(20, min_periods=20)
        .mean()
        .reset_index(level=0, drop=True)
        .where(amount_span.eq(19))
    )
    short_turnover = (
        grouped["turnover"].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)
    )
    prior_long_turnover = grouped["turnover"].transform(
        lambda series: series.rolling(20, min_periods=20).mean().shift(5)
    )
    turnover_surprise_span = position - grouped["_trade_date_position"].shift(24)
    turnover_surprise = np.log(short_turnover / prior_long_turnover).replace(
        [np.inf, -np.inf], np.nan
    )
    factors["turnover_surprise_5d_20d"] = turnover_surprise.where(turnover_surprise_span.eq(24))
    factors["max_return_20d"] = (
        daily_return.groupby(factors["symbol"], sort=False)
        .rolling(20, min_periods=20)
        .max()
        .reset_index(level=0, drop=True)
        .where(amount_span.eq(19))
    )
    return factors.drop(columns="_trade_date_position")
