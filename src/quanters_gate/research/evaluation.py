# 评估因子的 Rank IC 和分组收益。

from collections.abc import Sequence
from itertools import combinations

import numpy as np
import pandas as pd

from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.data.universe import normalize_symbol_values, select_eligible_signals
from quanters_gate.validation import (
    require_columns,
    require_positive,
    require_unique_rows,
    validate_non_overlapping_sample,
)

RANK_IC_COLUMNS = ["date", "factor", "rank_ic"]
QUANTILE_RETURN_COLUMNS = ["date", "factor", "quantile", "forward_return"]
FACTOR_RANK_CORRELATION_COLUMNS = ["date", "factor_left", "factor_right", "rank_correlation"]


def _prepare_evaluation_input(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    horizon: int,
) -> tuple[pd.DataFrame, list[str], str]:
    require_positive(horizon, "未来收益周期")
    factors = list(factor_columns)
    if not factors:
        raise ValueError("因子列不能为空。")
    if len(factors) != len(set(factors)):
        raise ValueError("因子列包含重复项。")
    target = f"forward_return_{horizon}d"
    require_columns(data, ("date", "symbol", target, *factors), "因子评估输入")
    prepared = data.copy()
    prepared["date"] = normalize_required_trade_dates(prepared["date"], "因子评估输入")
    prepared["symbol"] = normalize_symbol_values(prepared["symbol"], "因子评估输入")
    require_unique_rows(prepared, ("date", "symbol"), "因子评估输入")
    return select_eligible_signals(prepared), factors, target


def _sampled_date_groups(
    data: pd.DataFrame,
    sample_step: int,
) -> list[tuple[object, pd.DataFrame]]:
    require_positive(sample_step, "抽样步长")
    dates = sorted(data["date"].dropna().unique())[::sample_step]
    sampled = data.loc[data["date"].isin(dates)]
    return list(sampled.groupby("date", sort=True, observed=True))


def calculate_rank_ic(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    horizon: int,
    sample_step: int,
) -> pd.DataFrame:
    # 计算非重叠横截面的 Spearman Rank IC。
    validate_non_overlapping_sample(horizon, sample_step)
    eligible, factors, target = _prepare_evaluation_input(data, factor_columns, horizon)
    date_groups = _sampled_date_groups(eligible, sample_step)

    records: list[dict[str, object]] = []
    for factor in factors:
        for date, group in date_groups:
            cross_section = group[[factor, target]].dropna()
            if len(cross_section) < 3 or cross_section[factor].nunique() < 2:
                continue
            rank_ic = cross_section.corr(method="spearman").iloc[0, 1]
            if pd.notna(rank_ic):
                records.append({"date": date, "factor": factor, "rank_ic": rank_ic})
    return pd.DataFrame(records, columns=RANK_IC_COLUMNS)


def summarize_rank_ic(rank_ic: pd.DataFrame) -> pd.DataFrame:
    # 汇总每个因子的 IC 均值、稳定性和正值比例。
    columns = ["factor", "mean_rank_ic", "rank_ic_std", "count", "ic_ir", "positive_rate"]
    if rank_ic.empty:
        return pd.DataFrame(columns=columns)
    require_columns(rank_ic, ("factor", "rank_ic"), "Rank IC 数据")

    summary = rank_ic.groupby("factor", sort=True)["rank_ic"].agg(["mean", "std", "count"])
    summary["ic_ir"] = (summary["mean"] / summary["std"]).replace([np.inf, -np.inf], np.nan)
    positive_rate = (
        rank_ic.assign(positive=rank_ic["rank_ic"] > 0).groupby("factor")["positive"].mean()
    )
    summary["positive_rate"] = positive_rate
    return summary.rename(columns={"mean": "mean_rank_ic", "std": "rank_ic_std"}).reset_index()


def summarize_rank_ic_by_year(rank_ic: pd.DataFrame) -> pd.DataFrame:
    # 按自然年汇总非重叠 Rank IC，检查因子是否依赖单一年度。
    columns = [
        "factor",
        "year",
        "mean_rank_ic",
        "rank_ic_std",
        "count",
        "rank_ic_t_stat",
        "positive_rate",
    ]
    if rank_ic.empty:
        return pd.DataFrame(columns=columns)
    require_columns(rank_ic, ("date", "factor", "rank_ic"), "Rank IC 数据")
    prepared = rank_ic.copy()
    prepared["date"] = normalize_required_trade_dates(prepared["date"], "Rank IC 数据")
    prepared["year"] = prepared["date"].dt.year
    summary = prepared.groupby(["factor", "year"], sort=True)["rank_ic"].agg(
        ["mean", "std", "count"]
    )
    summary["rank_ic_t_stat"] = (
        summary["mean"] / (summary["std"] / np.sqrt(summary["count"]))
    ).replace([np.inf, -np.inf], np.nan)
    summary["positive_rate"] = (
        prepared.assign(positive=prepared["rank_ic"] > 0)
        .groupby(["factor", "year"])["positive"]
        .mean()
    )
    return summary.rename(columns={"mean": "mean_rank_ic", "std": "rank_ic_std"}).reset_index()


def calculate_factor_rank_correlations(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    horizon: int,
) -> pd.DataFrame:
    # 计算每个信号日横截面内不同因子的 Spearman 相关性。
    eligible, factors, _ = _prepare_evaluation_input(data, factor_columns, horizon)
    records: list[dict[str, object]] = []
    for date, group in eligible.groupby("date", sort=True):
        for factor_left, factor_right in combinations(factors, 2):
            pair = group[[factor_left, factor_right]].dropna()
            if len(pair) < 3 or pair[factor_left].nunique() < 2 or pair[factor_right].nunique() < 2:
                continue
            correlation = pair.corr(method="spearman").iloc[0, 1]
            if pd.notna(correlation):
                records.append(
                    {
                        "date": date,
                        "factor_left": factor_left,
                        "factor_right": factor_right,
                        "rank_correlation": correlation,
                    }
                )
    return pd.DataFrame(records, columns=FACTOR_RANK_CORRELATION_COLUMNS)


def summarize_factor_rank_correlations(correlations: pd.DataFrame) -> pd.DataFrame:
    # 汇总因子之间的日度横截面相关性，用于识别重复暴露。
    columns = [
        "factor_left",
        "factor_right",
        "mean_rank_correlation",
        "rank_correlation_std",
        "observation_count",
    ]
    if correlations.empty:
        return pd.DataFrame(columns=columns)
    require_columns(
        correlations,
        ("factor_left", "factor_right", "rank_correlation"),
        "因子相关性数据",
    )
    return (
        correlations.groupby(["factor_left", "factor_right"], sort=True)["rank_correlation"]
        .agg(
            mean_rank_correlation="mean",
            rank_correlation_std="std",
            observation_count="count",
        )
        .reset_index()
    )


def calculate_quantile_returns(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    horizon: int,
    quantile_count: int,
    sample_step: int,
) -> pd.DataFrame:
    # 在非重叠日期上计算等权因子分组收益。
    validate_non_overlapping_sample(horizon, sample_step)
    eligible, factors, target = _prepare_evaluation_input(data, factor_columns, horizon)
    require_positive(quantile_count, "分组数量")
    if quantile_count < 2:
        raise ValueError("分组数量至少为 2。")
    date_groups = _sampled_date_groups(eligible, sample_step)

    records: list[dict[str, object]] = []
    for factor in factors:
        for date, group in date_groups:
            usable = group[[factor, target]].dropna()
            if len(usable) < quantile_count or usable[factor].nunique() < quantile_count:
                continue
            labels = pd.qcut(usable[factor].rank(method="first"), quantile_count, labels=False) + 1
            for quantile, quantile_group in usable.groupby(labels, observed=True):
                records.append(
                    {
                        "date": date,
                        "factor": factor,
                        "quantile": int(quantile),
                        "forward_return": quantile_group[target].mean(),
                    }
                )
    return pd.DataFrame(records, columns=QUANTILE_RETURN_COLUMNS)


def summarize_quantile_returns(quantile_returns: pd.DataFrame) -> pd.DataFrame:
    # 汇总每个因子分组的平均未来收益。
    columns = ["factor", "quantile", "mean_forward_return", "observation_count"]
    if quantile_returns.empty:
        return pd.DataFrame(columns=columns)
    require_columns(
        quantile_returns,
        ("factor", "quantile", "forward_return"),
        "分组收益数据",
    )
    return (
        quantile_returns.groupby(["factor", "quantile"])["forward_return"]
        .agg(mean_forward_return="mean", observation_count="count")
        .reset_index()
    )


def summarize_top_bottom_spreads(
    quantile_summary: pd.DataFrame,
    quantile_count: int,
) -> pd.DataFrame:
    # 汇总最高组与最低组的收益差。
    require_positive(quantile_count, "分组数量")
    if quantile_count < 2:
        raise ValueError("分组数量至少为 2。")
    columns = ["factor", "low_quantile_return", "high_quantile_return", "top_bottom_spread"]
    if quantile_summary.empty:
        return pd.DataFrame(columns=columns)
    require_columns(
        quantile_summary,
        ("factor", "quantile", "mean_forward_return"),
        "分组收益摘要",
    )

    pivot = quantile_summary.pivot(index="factor", columns="quantile", values="mean_forward_return")
    if 1 not in pivot.columns or quantile_count not in pivot.columns:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(
        {
            "low_quantile_return": pivot[1],
            "high_quantile_return": pivot[quantile_count],
        }
    )
    result["top_bottom_spread"] = result["high_quantile_return"] - result["low_quantile_return"]
    return result.reset_index()


def build_factor_diagnostic_summary(
    rank_ic: pd.DataFrame,
    quantile_summary: pd.DataFrame,
    quantile_count: int,
) -> pd.DataFrame:
    # 合并 IC、显著性和分组单调性，供研究阶段人工筛选因子。
    columns = [
        "factor",
        "mean_rank_ic",
        "rank_ic_std",
        "ic_count",
        "ic_ir",
        "rank_ic_t_stat",
        "positive_rate",
        "low_quantile_return",
        "high_quantile_return",
        "top_bottom_spread",
        "quantile_monotonicity",
    ]
    rank_summary = summarize_rank_ic(rank_ic).rename(columns={"count": "ic_count"})
    if rank_summary.empty:
        return pd.DataFrame(columns=columns)

    rank_summary["rank_ic_t_stat"] = (
        rank_summary["mean_rank_ic"]
        / (rank_summary["rank_ic_std"] / np.sqrt(rank_summary["ic_count"]))
    ).replace([np.inf, -np.inf], np.nan)

    spreads = summarize_top_bottom_spreads(quantile_summary, quantile_count)
    monotonicity_rows: list[dict[str, object]] = []
    for factor, group in quantile_summary.groupby("factor", sort=True):
        usable = group[["quantile", "mean_forward_return"]].dropna()
        correlation = np.nan
        if len(usable) >= 3 and usable["quantile"].nunique() >= 3:
            correlation = usable.corr(method="spearman").iloc[0, 1]
        monotonicity_rows.append({"factor": factor, "quantile_monotonicity": correlation})
    monotonicity = pd.DataFrame(monotonicity_rows, columns=["factor", "quantile_monotonicity"])

    result = rank_summary.merge(spreads, on="factor", how="left").merge(
        monotonicity,
        on="factor",
        how="left",
    )
    return result.reindex(columns=columns).sort_values("factor").reset_index(drop=True)
