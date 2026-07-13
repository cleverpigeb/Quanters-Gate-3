import numpy as np
import pandas as pd


REQUIRED_ID_COLUMNS = ("date", "symbol")


def _validate_factor_panel(data: pd.DataFrame, factor_columns: list[str]) -> None:
    missing_ids = set(REQUIRED_ID_COLUMNS).difference(data.columns)
    missing_factors = set(factor_columns).difference(data.columns)
    if missing_ids:
        raise ValueError(f"Factor panel is missing identifier columns: {missing_ids}")
    if missing_factors:
        raise ValueError(f"Factor panel is missing columns: {missing_factors}")
    if not factor_columns:
        raise ValueError("Factor column list cannot be empty.")
    if len(factor_columns) != len(set(factor_columns)):
        raise ValueError("Factor column list contains duplicates.")


def winsorize_mad(series: pd.Series, mad_scale: float = 3.0) -> pd.Series:
    """Clip a cross-section with median absolute deviation while retaining missing values."""
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if len(valid) < 3:
        return numeric

    median = valid.median()
    mad = (valid - median).abs().median()
    if pd.isna(mad) or mad == 0:
        return numeric
    robust_std = 1.4826 * mad
    return numeric.clip(median - mad_scale * robust_std, median + mad_scale * robust_std)


def zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    std = numeric.std(ddof=0)
    if pd.isna(std) or std == 0:
        return numeric * 0.0
    return (numeric - numeric.mean()) / std


def preprocess_factors(data: pd.DataFrame, factor_columns: list[str]) -> pd.DataFrame:
    """Apply date-wise MAD winsorization and z-score standardization to factor columns."""
    _validate_factor_panel(data, factor_columns)
    result = data.copy().sort_values(list(REQUIRED_ID_COLUMNS)).reset_index(drop=True)
    for column in factor_columns:
        result[column] = result.groupby("date")[column].transform(winsorize_mad)
        result[column] = result.groupby("date")[column].transform(zscore)
    return result


def build_preprocess_summary(data: pd.DataFrame, factor_columns: list[str]) -> pd.DataFrame:
    """Produce a small audit table for factor coverage before research analysis."""
    _validate_factor_panel(data, factor_columns)
    rows = []
    for column in factor_columns:
        series = data[column]
        daily_coverage = data.groupby("date")[column].count()
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
