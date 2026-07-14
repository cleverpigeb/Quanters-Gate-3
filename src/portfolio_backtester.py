import numpy as np
import pandas as pd


def _validate_backtest_input(
    data: pd.DataFrame,
    factor_weights: dict[str, float],
    horizon: int,
    top_n: int,
    return_column: str | None,
) -> str:
    if horizon <= 0:
        raise ValueError("Forward-return horizon must be positive.")
    if top_n <= 0:
        raise ValueError("Portfolio top_n must be positive.")
    if not factor_weights:
        raise ValueError("Portfolio factor weights cannot be empty.")
    target = return_column or f"forward_return_{horizon}d"
    missing = {"date", "symbol", target, *factor_weights}.difference(data.columns)
    if missing:
        raise ValueError(f"Portfolio input is missing columns: {missing}")
    if any(not np.isfinite(weight) for weight in factor_weights.values()):
        raise ValueError("Portfolio factor weights must be finite.")
    return target


def _monthly_signal_dates(data: pd.DataFrame) -> list[pd.Timestamp]:
    dates = pd.to_datetime(data["date"], errors="coerce").dropna()
    return dates.groupby(dates.dt.to_period("M")).max().tolist()


def _turnover(previous_holdings: set[str], holdings: set[str]) -> float:
    if not previous_holdings:
        return 1.0
    return 1 - len(previous_holdings & holdings) / len(previous_holdings)


def run_monthly_top_n_backtest(
    data: pd.DataFrame,
    factor_weights: dict[str, float],
    horizon: int,
    top_n: int,
    return_column: str | None = None,
    one_way_cost_rate: float = 0.0,
) -> pd.DataFrame:
    """Run an equal-weight monthly Top N research backtest on forward returns.

    Returns are measured from the signal-date close. This is a factor-research
    diagnostic, not an execution-aware trading simulation.
    """
    target = _validate_backtest_input(data, factor_weights, horizon, top_n, return_column)
    if one_way_cost_rate < 0:
        raise ValueError("One-way cost rate cannot be negative.")
    result = data.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["symbol"] = result["symbol"].astype("string")
    result = result.dropna(subset=["date", "symbol"])

    records: list[dict[str, object]] = []
    previous_holdings: set[str] = set()
    columns = [*factor_weights, target]
    for date in _monthly_signal_dates(result):
        cross_section = result.loc[result["date"] == date].copy()
        if "is_tradable" in cross_section.columns:
            cross_section = cross_section.loc[cross_section["is_tradable"].fillna(False)]
        usable = cross_section.dropna(subset=columns)
        if usable.empty:
            continue

        usable["composite_score"] = sum(usable[column] * weight for column, weight in factor_weights.items())
        holdings_frame = usable.sort_values(["composite_score", "symbol"], ascending=[False, True]).head(top_n)
        holdings = set(holdings_frame["symbol"].tolist())
        gross_return = holdings_frame[target].mean()
        benchmark_return = usable[target].mean()
        turnover = _turnover(previous_holdings, holdings)
        net_return = gross_return - turnover * one_way_cost_rate
        records.append(
            {
                "date": date,
                "gross_portfolio_return": gross_return,
                "transaction_cost": turnover * one_way_cost_rate,
                "portfolio_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "holding_count": len(holdings),
                "turnover": turnover,
            }
        )
        previous_holdings = holdings

    return pd.DataFrame(records)


def summarize_backtest(backtest: pd.DataFrame, periods_per_year: int = 12) -> pd.DataFrame:
    """Summarize portfolio and equal-weight-universe benchmark performance."""
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
    required = {"portfolio_return", "benchmark_return", "turnover"}
    missing = required.difference(backtest.columns)
    if missing:
        raise ValueError(f"Backtest data is missing columns: {missing}")
    if periods_per_year <= 0:
        raise ValueError("Periods per year must be positive.")

    observations = len(backtest)
    portfolio_nav = (1 + backtest["portfolio_return"]).cumprod()
    benchmark_nav = (1 + backtest["benchmark_return"]).cumprod()
    portfolio_total = portfolio_nav.iloc[-1] - 1
    benchmark_total = benchmark_nav.iloc[-1] - 1
    annualized_portfolio = portfolio_nav.iloc[-1] ** (periods_per_year / observations) - 1
    annualized_benchmark = benchmark_nav.iloc[-1] ** (periods_per_year / observations) - 1
    drawdown = portfolio_nav / portfolio_nav.cummax() - 1
    return pd.DataFrame(
        [
            {
                "observation_count": observations,
                "portfolio_total_return": portfolio_total,
                "benchmark_total_return": benchmark_total,
                "excess_total_return": portfolio_total - benchmark_total,
                "portfolio_annualized_return": annualized_portfolio,
                "benchmark_annualized_return": annualized_benchmark,
                "portfolio_annualized_volatility": backtest["portfolio_return"].std(ddof=0)
                * np.sqrt(periods_per_year),
                "portfolio_max_drawdown": drawdown.min(),
                "mean_turnover": backtest["turnover"].mean(),
            }
        ]
    )
