import pandas as pd


def _validate_quantile_input(
    data: pd.DataFrame,
    factor_columns: list[str],
    horizon: int,
    quantile_count: int,
) -> str:
    if horizon <= 0:
        raise ValueError("Forward-return horizon must be positive.")
    if quantile_count < 2:
        raise ValueError("Quantile count must be at least two.")
    target = f"forward_return_{horizon}d"
    missing = {"date", target, *factor_columns}.difference(data.columns)
    if missing:
        raise ValueError(f"Quantile input is missing columns: {missing}")
    return target


def calculate_quantile_returns(
    data: pd.DataFrame,
    factor_columns: list[str],
    horizon: int,
    quantile_count: int,
) -> pd.DataFrame:
    """Evaluate equal-weighted future returns for each factor quantile by date."""
    target = _validate_quantile_input(data, factor_columns, horizon, quantile_count)
    records: list[dict[str, object]] = []
    for factor in factor_columns:
        for date, cross_section in data.groupby("date"):
            usable = cross_section[[factor, target]].dropna()
            if len(usable) < quantile_count or usable[factor].nunique() < quantile_count:
                continue
            labels = pd.qcut(usable[factor].rank(method="first"), quantile_count, labels=False) + 1
            for quantile, group in usable.groupby(labels, observed=True):
                records.append(
                    {
                        "date": date,
                        "factor": factor,
                        "quantile": int(quantile),
                        "forward_return": group[target].mean(),
                    }
                )
    return pd.DataFrame(records)


def summarize_quantile_returns(quantile_returns: pd.DataFrame) -> pd.DataFrame:
    """Return average future return for every factor-quantile combination."""
    if quantile_returns.empty:
        return pd.DataFrame(columns=["factor", "quantile", "mean_forward_return", "observation_count"])
    required = {"factor", "quantile", "forward_return"}
    missing = required.difference(quantile_returns.columns)
    if missing:
        raise ValueError(f"Quantile-return data is missing columns: {missing}")
    return (
        quantile_returns.groupby(["factor", "quantile"])["forward_return"]
        .agg(mean_forward_return="mean", observation_count="count")
        .reset_index()
    )


def summarize_top_bottom_spreads(
    quantile_summary: pd.DataFrame,
    quantile_count: int,
) -> pd.DataFrame:
    """Summarize the return spread between the highest and lowest factor quantiles."""
    if quantile_summary.empty:
        return pd.DataFrame(columns=["factor", "low_quantile_return", "high_quantile_return", "top_bottom_spread"])
    required = {"factor", "quantile", "mean_forward_return"}
    missing = required.difference(quantile_summary.columns)
    if missing:
        raise ValueError(f"Quantile summary is missing columns: {missing}")

    pivot = quantile_summary.pivot(index="factor", columns="quantile", values="mean_forward_return")
    if 1 not in pivot.columns or quantile_count not in pivot.columns:
        return pd.DataFrame(columns=["factor", "low_quantile_return", "high_quantile_return", "top_bottom_spread"])
    result = pd.DataFrame(
        {
            "low_quantile_return": pivot[1],
            "high_quantile_return": pivot[quantile_count],
        }
    )
    result["top_bottom_spread"] = result["high_quantile_return"] - result["low_quantile_return"]
    return result.reset_index()
