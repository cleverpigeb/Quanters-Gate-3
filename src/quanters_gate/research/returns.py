# 计算研究口径的未来收益。

import pandas as pd

from quanters_gate.validation import require_columns, require_positive


def add_forward_returns(data: pd.DataFrame, horizon: int) -> pd.DataFrame:
    # 按完整个股历史附加未来收盘收益，不移动因子日期。
    require_columns(data, ("date", "symbol", "close"), "未来收益输入")
    require_positive(horizon, "未来收益周期")

    result = data.copy().sort_values(["symbol", "date"]).reset_index(drop=True)
    future_close = result.groupby("symbol", sort=False)["close"].shift(-horizon)
    result[f"forward_return_{horizon}d"] = future_close / result["close"] - 1
    return result
