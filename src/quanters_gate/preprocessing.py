"""执行横截面因子预处理和覆盖率审计。"""

from collections.abc import Sequence

import pandas as pd

from quanters_gate.validation import require_columns, require_positive_finite

REQUIRED_ID_COLUMNS = ("date", "symbol")
MAD_TO_STANDARD_DEVIATION = 1.4826


def _validate_factor_panel(data: pd.DataFrame, factor_columns: Sequence[str]) -> list[str]:
    columns = list(factor_columns)
    if not columns:
        raise ValueError("因子列不能为空。")
    if len(columns) != len(set(columns)):
        raise ValueError("因子列包含重复项。")
    require_columns(data, REQUIRED_ID_COLUMNS, "因子面板")
    require_columns(data, columns, "因子面板")
    return columns


def winsorize_mad(series: pd.Series, mad_scale: float = 3.0) -> pd.Series:
    """使用中位数绝对偏差缩尾，同时保留缺失值。"""
    require_positive_finite(mad_scale, "MAD 缩尾倍数")
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if len(valid) < 3:
        return numeric

    median = valid.median()
    mad = (valid - median).abs().median()
    if pd.isna(mad) or mad == 0:
        return numeric
    robust_std = MAD_TO_STANDARD_DEVIATION * mad
    return numeric.clip(median - mad_scale * robust_std, median + mad_scale * robust_std)


def zscore(series: pd.Series) -> pd.Series:
    """使用总体标准差计算 z-score，并稳定处理常数截面。"""
    numeric = pd.to_numeric(series, errors="coerce")
    std = numeric.std(ddof=0)
    if pd.isna(std) or std == 0:
        return numeric * 0.0
    return (numeric - numeric.mean()) / std


def preprocess_factors(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    mad_scale: float = 3.0,
) -> pd.DataFrame:
    """按交易日批量执行 MAD 去极值和 z-score 标准化。"""
    require_positive_finite(mad_scale, "MAD 缩尾倍数")
    columns = _validate_factor_panel(data, factor_columns)
    result = data.copy().sort_values(list(REQUIRED_ID_COLUMNS)).reset_index(drop=True)
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
    """汇总各因子的缺失率和横截面覆盖情况。"""
    columns = _validate_factor_panel(data, factor_columns)
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
