# 计算执行口径的未来收益。

import numpy as np
import pandas as pd

from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.data.universe import normalize_symbol_values
from quanters_gate.validation import (
    normalize_boolean_values,
    require_columns,
    require_positive,
    require_unique_rows,
)


def add_next_open_execution_returns(
    signals: pd.DataFrame,
    execution_bars: pd.DataFrame,
    horizon: int,
) -> pd.DataFrame:
    # 使用未复权价格附加次日开盘至未来开盘收益。
    require_positive(horizon, "执行收益周期")
    require_columns(signals, ("date", "symbol"), "信号数据")
    require_columns(
        execution_bars,
        ("date", "symbol", "open", "is_tradable", "price_type"),
        "执行行情",
    )
    if execution_bars.empty:
        raise ValueError("执行行情不能为空。")
    price_types = execution_bars["price_type"].astype("string")
    if price_types.isna().any() or not price_types.eq("ex_rights").all():
        raise ValueError("执行行情必须全部使用 ex_rights 未复权价格。")

    signal_data = signals.copy()
    signal_data["date"] = normalize_required_trade_dates(signal_data["date"], "信号数据")
    signal_data["symbol"] = normalize_symbol_values(signal_data["symbol"], "信号数据")
    require_unique_rows(signal_data, ("date", "symbol"), "信号数据")

    bars = execution_bars.copy()
    bars["date"] = normalize_required_trade_dates(bars["date"], "执行行情")
    bars["symbol"] = normalize_symbol_values(bars["symbol"], "执行行情")
    require_unique_rows(bars, ("date", "symbol"), "执行行情")
    bars["open"] = pd.to_numeric(bars["open"], errors="coerce")
    bars["open"] = bars["open"].where(np.isfinite(bars["open"]) & bars["open"].gt(0))
    bars["is_tradable"] = normalize_boolean_values(bars["is_tradable"], "执行行情可交易性标记")
    signal_data["_has_execution_signal_date"] = signal_data["date"].isin(bars["date"])

    calendar = pd.DataFrame(
        {
            "date": pd.Index(
                pd.concat([signal_data["date"], bars["date"]], ignore_index=True).unique()
            ).sort_values()
        }
    )
    calendar["entry_date"] = calendar["date"].shift(-1)
    calendar["exit_date"] = calendar["date"].shift(-(horizon + 1))
    result = signal_data.merge(calendar, on="date", how="left", validate="many_to_one")
    result.loc[
        ~result["_has_execution_signal_date"],
        ["entry_date", "exit_date"],
    ] = pd.NaT

    entry = bars[["date", "symbol", "open", "is_tradable"]].rename(
        columns={"date": "entry_date", "open": "entry_open", "is_tradable": "entry_tradable"}
    )
    exit_data = bars[["date", "symbol", "open", "is_tradable"]].rename(
        columns={"date": "exit_date", "open": "exit_open", "is_tradable": "exit_tradable"}
    )
    result = result.merge(
        entry,
        on=["entry_date", "symbol"],
        how="left",
        validate="many_to_one",
    ).merge(
        exit_data,
        on=["exit_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    ready = result["entry_tradable"].fillna(False) & result["exit_tradable"].fillna(False)
    result["execution_return"] = (result["exit_open"] / result["entry_open"] - 1).where(ready)
    return result.drop(columns=["_has_execution_signal_date", "entry_date", "exit_date"])
