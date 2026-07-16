# 计算研究口径的未来收益。

import pandas as pd

from quanters_gate.data.dates import normalize_trade_dates_with_positions
from quanters_gate.data.universe import normalize_symbol_values
from quanters_gate.validation import require_columns, require_positive, require_unique_rows


def add_forward_returns(data: pd.DataFrame, horizon: int) -> pd.DataFrame:
    # 按完整个股历史附加未来收盘收益，不移动因子日期。
    require_columns(data, ("date", "symbol", "close"), "未来收益输入")
    require_positive(horizon, "未来收益周期")

    result = data.copy()
    result["date"], result["_trade_date_position"] = normalize_trade_dates_with_positions(
        result["date"],
        "未来收益输入",
    )
    result["symbol"] = normalize_symbol_values(result["symbol"], "未来收益输入")
    result = result.sort_values(["symbol", "date"]).reset_index(drop=True)
    require_unique_rows(result, ("date", "symbol"), "未来收益输入")
    grouped = result.groupby("symbol", sort=False)
    future_close = grouped["close"].shift(-horizon)
    future_position = grouped["_trade_date_position"].shift(-horizon)
    complete_window = (future_position - result["_trade_date_position"]).eq(horizon)
    result[f"forward_return_{horizon}d"] = (future_close / result["close"] - 1).where(
        complete_window
    )
    return result.drop(columns="_trade_date_position")
