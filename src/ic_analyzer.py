import pandas as pd


def add_forward_returns(data: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Attach future close-to-close returns without changing factor availability dates."""
    result = data.copy().sort_values(["symbol", "date"])
    future_close = result.groupby("symbol")["close"].shift(-horizon)
    result[f"forward_return_{horizon}d"] = future_close / result["close"] - 1
    return result


def calculate_rank_ic(
    data: pd.DataFrame,
    factor_columns: list[str],
    horizon: int,
    sample_step: int,
) -> pd.DataFrame:
    """Calculate non-overlapping cross-sectional Spearman Rank IC observations."""
    target = f"forward_return_{horizon}d"
    dates = sorted(data["date"].dropna().unique())[::sample_step]
    records: list[dict[str, object]] = []
    for factor in factor_columns:
        for date in dates:
            cross_section = data.loc[data["date"] == date, [factor, target]].dropna()
            if len(cross_section) < 3 or cross_section[factor].nunique() < 2:
                continue
            value = cross_section.corr(method="spearman").iloc[0, 1]
            records.append({"date": date, "factor": factor, "rank_ic": value})
    return pd.DataFrame(records).dropna(subset=["rank_ic"])


def summarize_rank_ic(rank_ic: pd.DataFrame) -> pd.DataFrame:
    """Summarize IC mean, stability and positive-rate for each factor."""
    summary = rank_ic.groupby("factor")["rank_ic"].agg(["mean", "std", "count"])
    summary["ic_ir"] = summary["mean"] / summary["std"]
    summary["positive_rate"] = rank_ic.groupby("factor")["rank_ic"].apply(lambda values: (values > 0).mean())
    return summary.rename(columns={"mean": "mean_rank_ic", "std": "rank_ic_std"}).reset_index()
