# 计算执行口径的未来收益。

import numpy as np
import pandas as pd

from quanters_gate.data.dates import normalize_trade_dates
from quanters_gate.validation import require_columns, require_positive, require_unique_rows


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
    if not execution_bars["price_type"].eq("ex_rights").all():
        raise ValueError("执行行情必须全部使用 ex_rights 未复权价格。")

    signal_data = signals.copy()
    signal_data["date"] = normalize_trade_dates(signal_data["date"])
    signal_data["symbol"] = signal_data["symbol"].astype("string").str.strip()
    if signal_data[["date", "symbol"]].isna().any().any():
        raise ValueError("信号数据包含无效日期或股票代码。")
    require_unique_rows(signal_data, ("date", "symbol"), "信号数据")

    bars = execution_bars.copy()
    bars["date"] = normalize_trade_dates(bars["date"])
    bars["symbol"] = bars["symbol"].astype("string").str.strip()
    bars["open"] = pd.to_numeric(bars["open"], errors="coerce")
    bars["open"] = bars["open"].where(np.isfinite(bars["open"]) & bars["open"].gt(0))

    tradable = bars["is_tradable"].astype("string").str.strip().str.lower()
    tradable_mapping = {"true": True, "false": False, "1": True, "0": False}
    invalid_tradable = tradable.notna() & ~tradable.isin(tradable_mapping)
    if invalid_tradable.any():
        raise ValueError("执行行情包含无法识别的可交易性标记。")
    bars["is_tradable"] = tradable.map(tradable_mapping).fillna(False).astype(bool)
    bars = (
        bars.dropna(subset=["date", "symbol", "open"])
        .sort_values(["symbol", "date"])
        .drop_duplicates(["date", "symbol"], keep="last")
    )
    grouped = bars.groupby("symbol", sort=False)
    bars["entry_open"] = grouped["open"].shift(-1)
    bars["exit_open"] = grouped["open"].shift(-(horizon + 1))
    bars["entry_tradable"] = grouped["is_tradable"].shift(-1)
    bars["exit_tradable"] = grouped["is_tradable"].shift(-(horizon + 1))

    execution = bars[
        ["date", "symbol", "entry_open", "exit_open", "entry_tradable", "exit_tradable"]
    ]
    result = signal_data.merge(
        execution,
        on=["date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    ready = result["entry_tradable"].fillna(False) & result["exit_tradable"].fillna(False)
    result["execution_return"] = (result["exit_open"] / result["entry_open"] - 1).where(ready)
    return result
