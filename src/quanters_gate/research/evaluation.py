# 评估因子的 Rank IC 和分组收益。

from collections.abc import Sequence

import numpy as np
import pandas as pd

from quanters_gate.data.universe import select_eligible_signals
from quanters_gate.validation import require_columns, require_positive

RANK_IC_COLUMNS = ["date", "factor", "rank_ic"]
QUANTILE_RETURN_COLUMNS = ["date", "factor", "quantile", "forward_return"]


def _validate_evaluation_input(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    horizon: int,
) -> tuple[list[str], str]:
    require_positive(horizon, "未来收益周期")
    factors = list(factor_columns)
    if not factors:
        raise ValueError("因子列不能为空。")
    if len(factors) != len(set(factors)):
        raise ValueError("因子列包含重复项。")
    target = f"forward_return_{horizon}d"
    require_columns(data, ("date", target, *factors), "因子评估输入")
    return factors, target


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
    factors, target = _validate_evaluation_input(data, factor_columns, horizon)
    eligible = select_eligible_signals(data)
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


def calculate_quantile_returns(
    data: pd.DataFrame,
    factor_columns: Sequence[str],
    horizon: int,
    quantile_count: int,
    sample_step: int,
) -> pd.DataFrame:
    # 在非重叠日期上计算等权因子分组收益。
    factors, target = _validate_evaluation_input(data, factor_columns, horizon)
    if quantile_count < 2:
        raise ValueError("分组数量至少为 2。")
    eligible = select_eligible_signals(data)
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
