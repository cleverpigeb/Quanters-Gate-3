import numpy as np
import pandas as pd


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
    result = data.copy()
    for column in factor_columns:
        if column not in result.columns:
            raise ValueError(f"Factor column is missing: {column}")
        result[column] = result.groupby("date")[column].transform(winsorize_mad)
        result[column] = result.groupby("date")[column].transform(zscore)
    return result


def build_preprocess_summary(data: pd.DataFrame, factor_columns: list[str]) -> pd.DataFrame:
    """Produce a small audit table for factor coverage before research analysis."""
    rows = []
    for column in factor_columns:
        series = data[column]
        rows.append(
            {
                "factor": column,
                "missing_rate": series.isna().mean(),
                "observation_count": series.notna().sum(),
            }
        )
    return pd.DataFrame(rows)
