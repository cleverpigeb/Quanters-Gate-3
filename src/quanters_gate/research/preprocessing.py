# 执行横截面因子预处理和覆盖率审计。

from collections.abc import Sequence

import pandas as pd

from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.data.universe import normalize_symbol_values
from quanters_gate.validation import (
    require_columns,
    require_positive_finite,
    require_unique_rows,
)

REQUIRED_ID_COLUMNS = ("date", "symbol")
MAD_TO_STANDARD_DEVIATION = 1.4826


def _prepare_factor_panel(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
) -> tuple[pd.DataFrame, list[str]]:
    columns = list(factor_columns)
    if not columns:
        raise ValueError("因子列不能为空。")
    if len(columns) != len(set(columns)):
        raise ValueError("因子列包含重复项。")
    require_columns(data, REQUIRED_ID_COLUMNS, "因子面板")
    require_columns(data, columns, "因子面板")
    result = data.copy()
    result["date"] = normalize_required_trade_dates(result["date"], "因子面板")
    result["symbol"] = normalize_symbol_values(result["symbol"], "因子面板")
    require_unique_rows(result, REQUIRED_ID_COLUMNS, "因子面板")
    return result, columns


def preprocess_factors(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    mad_scale: float = 3.0,
) -> pd.DataFrame:
    # 按交易日批量执行 MAD 去极值和 z-score 标准化。
    require_positive_finite(mad_scale, "MAD 缩尾倍数")
    result, columns = _prepare_factor_panel(data, factor_columns)
    result = result.sort_values(list(REQUIRED_ID_COLUMNS)).reset_index(drop=True)
    numeric = result[columns].apply(pd.to_numeric, errors="coerce")
    dates = result["date"]

    grouped = numeric.groupby(dates, sort=False)
    median = grouped.transform("median")
    deviation = (numeric - median).abs()
    mad = deviation.groupby(dates, sort=False).transform("median")
    count = grouped.transform("count")
    robust_std = MAD_TO_STANDARD_DEVIATION * mad
    lower = median - mad_scale * robust_std
    upper = median + mad_scale * robust_std
    should_clip = (count >= 3) & mad.notna() & mad.ne(0)

    winsorized = numeric.mask(should_clip & numeric.lt(lower), lower)
    winsorized = winsorized.mask(should_clip & winsorized.gt(upper), upper)

    standardized_groups = winsorized.groupby(dates, sort=False)
    mean = standardized_groups.transform("mean")
    std = standardized_groups.transform("std", ddof=0)
    standardized = (winsorized - mean) / std
    degenerate = std.isna() | std.eq(0)
    result[columns] = standardized.mask(degenerate, winsorized * 0.0)
    return result


def build_preprocess_summary(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
) -> pd.DataFrame:
    # 汇总各因子的缺失率和横截面覆盖情况。
    data, columns = _prepare_factor_panel(data, factor_columns)
    rows: list[dict[str, object]] = []
    for column in columns:
        series = data[column]
        daily_coverage = data.groupby("date", sort=False)[column].count()
        rows.append(
            {
                "factor": column,
                "missing_rate": series.isna().mean(),
                "observation_count": series.notna().sum(),
                "usable_date_count": (daily_coverage > 0).sum(),
                "median_cross_section_size": daily_coverage.median(),
            }
        )
    return pd.DataFrame(rows)
