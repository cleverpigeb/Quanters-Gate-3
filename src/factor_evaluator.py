import pandas as pd


def calculate_quantile_returns(
    data: pd.DataFrame,
    factor_columns: list[str],
    horizon: int,
    quantile_count: int,
) -> pd.DataFrame:
    """Evaluate equal-weighted future returns for each factor quantile by date."""
    target = f"forward_return_{horizon}d"
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
        return pd.DataFrame(columns=["factor", "quantile", "mean_forward_return"])
    return (
        quantile_returns.groupby(["factor", "quantile"])["forward_return"]
        .mean()
        .rename("mean_forward_return")
        .reset_index()
    )
