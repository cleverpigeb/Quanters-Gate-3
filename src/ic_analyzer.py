import pandas as pd


REQUIRED_COLUMNS = ("date", "symbol", "close")


def _validate_panel(data: pd.DataFrame, horizon: int) -> None:
    missing = set(REQUIRED_COLUMNS).difference(data.columns)
    if missing:
        raise ValueError(f"IC input is missing columns: {missing}")
    if horizon <= 0:
        raise ValueError("Forward-return horizon must be positive.")


def add_forward_returns(data: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Attach future close-to-close returns without changing factor availability dates."""
    _validate_panel(data, horizon)
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
    _validate_panel(data, horizon)
    if sample_step <= 0:
        raise ValueError("IC sample step must be positive.")
    target = f"forward_return_{horizon}d"
    if target not in data.columns:
        raise ValueError(f"IC input is missing target column: {target}")
    missing_factors = set(factor_columns).difference(data.columns)
    if missing_factors:
        raise ValueError(f"IC input is missing factor columns: {missing_factors}")
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
    columns = ["factor", "mean_rank_ic", "rank_ic_std", "count", "ic_ir", "positive_rate"]
    if rank_ic.empty:
        return pd.DataFrame(columns=columns)
    required = {"factor", "rank_ic"}
    missing = required.difference(rank_ic.columns)
    if missing:
        raise ValueError(f"Rank IC data is missing columns: {missing}")
    summary = rank_ic.groupby("factor")["rank_ic"].agg(["mean", "std", "count"])
    summary["ic_ir"] = summary["mean"] / summary["std"]
    summary["positive_rate"] = rank_ic.groupby("factor")["rank_ic"].apply(lambda values: (values > 0).mean())
    return summary.rename(columns={"mean": "mean_rank_ic", "std": "rank_ic_std"}).reset_index()
