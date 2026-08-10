# 执行月度 Top N 组合研究回测及其摘要计算。

from collections.abc import Mapping

import numpy as np
import pandas as pd

from quanters_gate.backtest.selection import (
    add_composite_score,
    monthly_signal_dates,
    normalize_active_factor_weights,
)
from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.data.universe import normalize_symbol_values, select_eligible_signals
from quanters_gate.validation import (
    normalize_boolean_values,
    require_columns,
    require_non_negative_finite,
    require_positive,
    require_unique_rows,
)

BACKTEST_COLUMNS = [
    "date",
    "gross_portfolio_return",
    "transaction_cost",
    "portfolio_return",
    "benchmark_return",
    "excess_return",
    "holding_count",
    "turnover",
]


def _validate_backtest_input(
    data: pd.DataFrame,
    factor_weights: Mapping[str, float],
    horizon: int,
    top_n: int,
    return_column: str | None,
) -> tuple[str, dict[str, float]]:
    require_positive(horizon, "未来收益周期")
    require_positive(top_n, "组合持仓数量")
    target = return_column or f"forward_return_{horizon}d"
    active_weights = normalize_active_factor_weights(data, factor_weights, "组合回测输入")
    require_columns(data, (target,), "组合回测输入")
    return target, active_weights


def _turnover(previous_holdings: set[str], holdings: set[str]) -> float:
    if not previous_holdings:
        return 1.0
    previous_weight = 1 / len(previous_holdings)
    current_weight = 1 / len(holdings)
    symbols = previous_holdings | holdings
    return 0.5 * sum(
        abs(
            (current_weight if symbol in holdings else 0.0)
            - (previous_weight if symbol in previous_holdings else 0.0)
        )
        for symbol in symbols
    )


def run_monthly_top_n_backtest(
    data: pd.DataFrame,
    factor_weights: Mapping[str, float],
    horizon: int,
    top_n: int,
    return_column: str | None = None,
    one_way_cost_rate: float = 0.0,
) -> pd.DataFrame:
    # 使用未来收益运行月度等权 Top N 组合研究回测。
    target, weights = _validate_backtest_input(
        data,
        factor_weights,
        horizon,
        top_n,
        return_column,
    )
    require_non_negative_finite(one_way_cost_rate, "单边成本率")
    if one_way_cost_rate > 1:
        raise ValueError("单边成本率不能大于 1。")

    result = select_eligible_signals(data)
    result["date"] = normalize_required_trade_dates(result["date"], "组合回测输入")
    result["symbol"] = normalize_symbol_values(result["symbol"], "组合回测输入")
    require_unique_rows(result, ("date", "symbol"), "组合回测输入")
    if "is_tradable" in result.columns:
        result["is_tradable"] = normalize_boolean_values(
            result["is_tradable"],
            "组合回测可交易性标记",
        )
    date_groups = {
        pd.Timestamp(date): group
        for date, group in result.groupby("date", sort=False, observed=True)
    }

    records: list[dict[str, object]] = []
    previous_holdings: set[str] = set()
    required_values = [*weights, target]
    for date in monthly_signal_dates(result):
        cross_section = date_groups[pd.Timestamp(date)]
        if "is_tradable" in cross_section.columns:
            cross_section = cross_section.loc[cross_section["is_tradable"]]
        usable = cross_section.dropna(subset=required_values).copy()
        if usable.empty:
            continue

        usable = add_composite_score(usable, weights)
        holdings_frame = usable.sort_values(
            ["composite_score", "symbol"],
            ascending=[False, True],
        ).head(top_n)
        holdings = set(holdings_frame["symbol"].tolist())
        gross_return = holdings_frame[target].mean()
        benchmark_return = usable[target].mean()
        turnover = _turnover(previous_holdings, holdings)
        transaction_cost = turnover * one_way_cost_rate
        net_return = gross_return - transaction_cost
        records.append(
            {
                "date": date,
                "gross_portfolio_return": gross_return,
                "transaction_cost": transaction_cost,
                "portfolio_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "holding_count": len(holdings),
                "turnover": turnover,
            }
        )
        previous_holdings = holdings

    return pd.DataFrame(records, columns=BACKTEST_COLUMNS)


def summarize_backtest(backtest: pd.DataFrame, periods_per_year: int = 12) -> pd.DataFrame:
    # 汇总组合与等权股票池基准的收益和风险。
    columns = [
        "observation_count",
        "portfolio_total_return",
        "benchmark_total_return",
        "excess_total_return",
        "portfolio_annualized_return",
        "benchmark_annualized_return",
        "portfolio_annualized_volatility",
        "portfolio_max_drawdown",
        "mean_turnover",
    ]
    if backtest.empty:
        return pd.DataFrame(columns=columns)
    require_columns(
        backtest,
        ("date", "portfolio_return", "benchmark_return", "turnover"),
        "回测数据",
    )
    require_positive(periods_per_year, "年化周期数")

    ordered = backtest.copy()
    ordered["date"] = normalize_required_trade_dates(ordered["date"], "回测数据")
    ordered = ordered.sort_values("date").reset_index(drop=True)
    require_unique_rows(ordered, ("date",), "回测数据")
    numeric_columns = ["portfolio_return", "benchmark_return", "turnover"]
    numeric = ordered[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric).all().all():
        raise ValueError("回测收益和换手率必须是有限数值。")
    if numeric[["portfolio_return", "benchmark_return"]].lt(-1).any().any():
        raise ValueError("回测收益率不能小于 -100%。")
    if numeric["turnover"].lt(0).any() or numeric["turnover"].gt(1).any():
        raise ValueError("回测换手率必须位于 0 到 1 之间。")
    ordered[numeric_columns] = numeric

    observations = len(ordered)
    portfolio_nav = (1 + ordered["portfolio_return"]).cumprod()
    benchmark_nav = (1 + ordered["benchmark_return"]).cumprod()
    portfolio_total = portfolio_nav.iloc[-1] - 1
    benchmark_total = benchmark_nav.iloc[-1] - 1
    annualized_portfolio = portfolio_nav.iloc[-1] ** (periods_per_year / observations) - 1
    annualized_benchmark = benchmark_nav.iloc[-1] ** (periods_per_year / observations) - 1
    drawdown = portfolio_nav / portfolio_nav.cummax().clip(lower=1.0) - 1

    return pd.DataFrame(
        [
            {
                "observation_count": observations,
                "portfolio_total_return": portfolio_total,
                "benchmark_total_return": benchmark_total,
                "excess_total_return": portfolio_total - benchmark_total,
                "portfolio_annualized_return": annualized_portfolio,
                "benchmark_annualized_return": annualized_benchmark,
                "portfolio_annualized_volatility": ordered["portfolio_return"].std(ddof=0)
                * np.sqrt(periods_per_year),
                "portfolio_max_drawdown": drawdown.min(),
                "mean_turnover": ordered["turnover"].mean(),
            }
        ]
    )
