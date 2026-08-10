# 复用组合选股所需的权重校验和月度信号日期逻辑。

from collections.abc import Mapping

import numpy as np
import pandas as pd

from quanters_gate.validation import require_columns


def normalize_active_factor_weights(
    data: pd.DataFrame,
    factor_weights: Mapping[str, float],
    context: str,
) -> dict[str, float]:
    # 校验组合因子权重，并移除不参与计算的零权重因子。
    if not factor_weights:
        raise ValueError("组合因子权重不能为空。")
    try:
        weights = {factor: float(weight) for factor, weight in factor_weights.items()}
    except TypeError, ValueError:
        raise ValueError("组合因子权重必须是有限数值。") from None
    if any(not np.isfinite(weight) for weight in weights.values()):
        raise ValueError("组合因子权重必须是有限数值。")
    active_weights = {factor: weight for factor, weight in weights.items() if weight != 0}
    if not active_weights:
        raise ValueError("组合因子权重不能全部为零。")
    require_columns(data, ("date", "symbol", *active_weights), context)
    return active_weights


def monthly_signal_dates(data: pd.DataFrame) -> list[pd.Timestamp]:
    # 返回每个自然月最后一个实际存在的信号日期。
    dates = data["date"].dropna()
    return dates.groupby(dates.dt.to_period("M")).max().tolist()


def add_composite_score(
    data: pd.DataFrame,
    factor_weights: Mapping[str, float],
) -> pd.DataFrame:
    # 按给定线性权重计算组合分数。
    result = data.copy()
    result["composite_score"] = sum(
        result[column] * weight for column, weight in factor_weights.items()
    )
    return result
