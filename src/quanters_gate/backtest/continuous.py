# 按相邻调仓日运行连续持仓、现金和净值回测。

from collections.abc import Mapping
from dataclasses import dataclass, field

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

CONTINUOUS_BACKTEST_COLUMNS = [
    "date",
    "portfolio_nav",
    "portfolio_return",
    "benchmark_nav",
    "benchmark_return",
    "excess_return",
    "cash_weight",
    "holding_count",
    "turnover",
    "transaction_cost",
    "is_rebalance_date",
    "signal_date",
    "blocked_buy_count",
    "blocked_sell_count",
    "stale_holding_count",
]

TRADE_COLUMNS = [
    "account",
    "date",
    "signal_date",
    "symbol",
    "side",
    "price",
    "shares",
    "gross_value",
    "transaction_cost",
]

HOLDING_COLUMNS = [
    "account",
    "date",
    "signal_date",
    "symbol",
    "shares",
    "price",
    "market_value",
    "target_weight",
    "actual_weight",
    "is_tradable",
    "is_selected",
]


@dataclass(frozen=True)
class ContinuousBacktestResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    holdings: pd.DataFrame


@dataclass
class _AccountState:
    cash: float = 1.0
    shares: dict[str, float] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class _RebalanceResult:
    turnover: float
    transaction_cost: float
    blocked_buy_count: int
    blocked_sell_count: int


def _normalize_market_bars(market_bars: pd.DataFrame) -> pd.DataFrame:
    require_columns(
        market_bars,
        ("date", "symbol", "open", "close", "is_tradable", "price_type"),
        "连续回测行情",
    )
    bars = market_bars.copy()
    bars["date"] = normalize_required_trade_dates(bars["date"], "连续回测行情")
    bars["symbol"] = normalize_symbol_values(bars["symbol"], "连续回测行情")
    require_unique_rows(bars, ("date", "symbol"), "连续回测行情")
    bars["open"] = pd.to_numeric(bars["open"], errors="coerce")
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    valid_prices = (
        np.isfinite(bars[["open", "close"]]).all(axis=1) & bars["open"].gt(0) & bars["close"].gt(0)
    )
    if not valid_prices.all():
        raise ValueError("连续回测行情包含无效的开盘价或收盘价。")
    bars["is_tradable"] = normalize_boolean_values(
        bars["is_tradable"],
        "连续回测行情可交易性标记",
    )
    price_types = bars["price_type"].astype("string")
    if price_types.isna().any() or not price_types.eq("lxr_fc_rights").all():
        raise ValueError("连续净值研究回测必须全部使用 lxr_fc_rights 前复权行情。")
    return bars.sort_values(["date", "symbol"]).reset_index(drop=True)


def _normalize_signals(
    signals: pd.DataFrame,
    factor_weights: Mapping[str, float],
) -> tuple[pd.DataFrame, dict[str, float]]:
    result = select_eligible_signals(signals)
    weights = normalize_active_factor_weights(result, factor_weights, "连续回测信号")
    result = result.copy()
    result["date"] = normalize_required_trade_dates(result["date"], "连续回测信号")
    result["symbol"] = normalize_symbol_values(result["symbol"], "连续回测信号")
    require_unique_rows(result, ("date", "symbol"), "连续回测信号")
    return result, weights


def _next_trade_date(
    signal_date: pd.Timestamp,
    calendar: pd.DatetimeIndex,
    end_date: pd.Timestamp,
) -> pd.Timestamp | None:
    position = int(calendar.searchsorted(signal_date, side="right"))
    if position >= len(calendar) or calendar[position] > end_date:
        return None
    return pd.Timestamp(calendar[position])


def _build_rebalance_schedule(
    signals: pd.DataFrame,
    weights: Mapping[str, float],
    calendar: pd.DatetimeIndex,
    top_n: int,
) -> dict[pd.Timestamp, tuple[pd.Timestamp, tuple[str, ...], tuple[str, ...]]]:
    require_positive(top_n, "组合持仓数量")
    end_date = pd.Timestamp(signals["date"].max())
    date_groups = {
        pd.Timestamp(date): group
        for date, group in signals.groupby("date", sort=False, observed=True)
    }
    schedule: dict[pd.Timestamp, tuple[pd.Timestamp, tuple[str, ...], tuple[str, ...]]] = {}
    for signal_date in monthly_signal_dates(signals):
        signal_date = pd.Timestamp(signal_date)
        if signal_date not in calendar:
            raise ValueError(f"连续回测行情缺少信号日期 {signal_date:%Y-%m-%d}。")
        trade_date = _next_trade_date(signal_date, calendar, end_date)
        if trade_date is None:
            continue
        cross_section = date_groups[signal_date]
        benchmark_symbols = tuple(sorted(cross_section["symbol"].drop_duplicates().tolist()))
        usable = cross_section.dropna(subset=list(weights)).copy()
        if usable.empty:
            portfolio_symbols: tuple[str, ...] = ()
        else:
            ranked = add_composite_score(usable, weights).sort_values(
                ["composite_score", "symbol"],
                ascending=[False, True],
            )
            portfolio_symbols = tuple(ranked.head(top_n)["symbol"].tolist())
        schedule[trade_date] = (signal_date, portfolio_symbols, benchmark_symbols)
    return schedule


def _mark_positions(
    state: _AccountState,
    day_bars: pd.DataFrame,
    price_column: str,
) -> tuple[float, dict[str, float], int]:
    market_values: dict[str, float] = {}
    stale_count = 0
    for symbol, shares in state.shares.items():
        if symbol in day_bars.index:
            price = float(day_bars.at[symbol, price_column])
        elif symbol in state.last_close:
            price = state.last_close[symbol]
            stale_count += 1
        else:
            raise ValueError(f"持仓 {symbol} 在连续回测中缺少可用估值价格。")
        market_values[symbol] = shares * price
    return state.cash + sum(market_values.values()), market_values, stale_count


def _record_trade(
    records: list[dict[str, object]],
    account: str,
    date: pd.Timestamp,
    signal_date: pd.Timestamp,
    symbol: str,
    side: str,
    price: float,
    shares: float,
    cost_rate: float,
) -> float:
    gross_value = shares * price
    transaction_cost = gross_value * cost_rate
    records.append(
        {
            "account": account,
            "date": date,
            "signal_date": signal_date,
            "symbol": symbol,
            "side": side,
            "price": price,
            "shares": shares,
            "gross_value": gross_value,
            "transaction_cost": transaction_cost,
        }
    )
    return transaction_cost


def _rebalance_account(
    account: str,
    state: _AccountState,
    targets: tuple[str, ...],
    day_bars: pd.DataFrame,
    open_values: dict[str, float],
    pretrade_nav: float,
    cost_rate: float,
    date: pd.Timestamp,
    signal_date: pd.Timestamp,
    trade_records: list[dict[str, object]],
) -> _RebalanceResult:
    target_set = set(targets)
    target_value = pretrade_nav / len(targets) if targets else 0.0
    planned_sells: dict[str, float] = {}
    planned_buys: dict[str, float] = {}
    blocked_buy_count = 0
    blocked_sell_count = 0

    for symbol in set(state.shares) | target_set:
        current_value = open_values.get(symbol, 0.0)
        desired_value = target_value if symbol in target_set else 0.0
        is_tradable = symbol in day_bars.index and bool(day_bars.at[symbol, "is_tradable"])
        difference = desired_value - current_value
        if not is_tradable:
            if difference > 1e-12:
                blocked_buy_count += 1
            elif difference < -1e-12:
                blocked_sell_count += 1
            continue
        if difference > 1e-12:
            planned_buys[symbol] = difference
        elif difference < -1e-12:
            planned_sells[symbol] = -difference

    gross_traded_value = 0.0
    transaction_cost = 0.0
    for symbol in sorted(planned_sells):
        price = float(day_bars.at[symbol, "open"])
        shares = min(planned_sells[symbol] / price, state.shares[symbol])
        gross_value = shares * price
        cost = _record_trade(
            trade_records,
            account,
            date,
            signal_date,
            symbol,
            "sell",
            price,
            shares,
            cost_rate,
        )
        state.cash += gross_value - cost
        remaining = state.shares[symbol] - shares
        if remaining <= 1e-12:
            state.shares.pop(symbol)
        else:
            state.shares[symbol] = remaining
        gross_traded_value += gross_value
        transaction_cost += cost

    planned_buy_value = sum(planned_buys.values())
    buy_scale = 0.0
    if planned_buy_value > 0:
        buy_scale = min(1.0, state.cash / (planned_buy_value * (1 + cost_rate)))
    for symbol in sorted(planned_buys):
        gross_value = planned_buys[symbol] * buy_scale
        if gross_value <= 1e-12:
            continue
        price = float(day_bars.at[symbol, "open"])
        shares = gross_value / price
        cost = _record_trade(
            trade_records,
            account,
            date,
            signal_date,
            symbol,
            "buy",
            price,
            shares,
            cost_rate,
        )
        state.cash -= gross_value + cost
        state.shares[symbol] = state.shares.get(symbol, 0.0) + shares
        gross_traded_value += gross_value
        transaction_cost += cost

    if abs(state.cash) < 1e-12:
        state.cash = 0.0
    return _RebalanceResult(
        turnover=gross_traded_value / pretrade_nav if pretrade_nav > 0 else 0.0,
        transaction_cost=transaction_cost,
        blocked_buy_count=blocked_buy_count,
        blocked_sell_count=blocked_sell_count,
    )


def _record_holdings(
    records: list[dict[str, object]],
    account: str,
    state: _AccountState,
    targets: tuple[str, ...],
    day_bars: pd.DataFrame,
    date: pd.Timestamp,
    signal_date: pd.Timestamp,
) -> None:
    nav, market_values, _ = _mark_positions(state, day_bars, "open")
    target_set = set(targets)
    target_weight = 1 / len(targets) if targets else 0.0
    for symbol in sorted(state.shares):
        price = market_values[symbol] / state.shares[symbol]
        records.append(
            {
                "account": account,
                "date": date,
                "signal_date": signal_date,
                "symbol": symbol,
                "shares": state.shares[symbol],
                "price": price,
                "market_value": market_values[symbol],
                "target_weight": target_weight if symbol in target_set else 0.0,
                "actual_weight": market_values[symbol] / nav if nav > 0 else np.nan,
                "is_tradable": symbol in day_bars.index
                and bool(day_bars.at[symbol, "is_tradable"]),
                "is_selected": symbol in target_set,
            }
        )


def _update_last_closes(state: _AccountState, day_bars: pd.DataFrame) -> None:
    for symbol in state.shares:
        if symbol in day_bars.index:
            state.last_close[symbol] = float(day_bars.at[symbol, "close"])


def run_continuous_top_n_backtest(
    signals: pd.DataFrame,
    market_bars: pd.DataFrame,
    factor_weights: Mapping[str, float],
    top_n: int,
    one_way_cost_rate: float = 0.0,
) -> ContinuousBacktestResult:
    # 月末生成信号，下一交易日开盘调仓，并逐日连续估值。
    require_non_negative_finite(one_way_cost_rate, "单边成本率")
    if one_way_cost_rate > 1:
        raise ValueError("单边成本率不能大于 1。")
    bars = _normalize_market_bars(market_bars)
    signal_data, weights = _normalize_signals(signals, factor_weights)
    calendar = pd.DatetimeIndex(bars["date"].drop_duplicates().sort_values())
    schedule = _build_rebalance_schedule(signal_data, weights, calendar, top_n)
    if not schedule:
        return ContinuousBacktestResult(
            daily=pd.DataFrame(columns=CONTINUOUS_BACKTEST_COLUMNS),
            trades=pd.DataFrame(columns=TRADE_COLUMNS),
            holdings=pd.DataFrame(columns=HOLDING_COLUMNS),
        )

    first_date = min(schedule)
    end_date = pd.Timestamp(signal_data["date"].max())
    calendar = calendar[(calendar >= first_date) & (calendar <= end_date)]
    bar_groups = {
        pd.Timestamp(date): group.set_index("symbol", drop=False)
        for date, group in bars.loc[bars["date"].isin(calendar)].groupby(
            "date", sort=False, observed=True
        )
    }
    portfolio_state = _AccountState()
    benchmark_state = _AccountState()
    previous_portfolio_nav = 1.0
    previous_benchmark_nav = 1.0
    daily_records: list[dict[str, object]] = []
    trade_records: list[dict[str, object]] = []
    holding_records: list[dict[str, object]] = []

    for date in calendar:
        date = pd.Timestamp(date)
        day_bars = bar_groups[date]
        portfolio_open_nav, portfolio_open_values, _ = _mark_positions(
            portfolio_state, day_bars, "open"
        )
        benchmark_open_nav, benchmark_open_values, _ = _mark_positions(
            benchmark_state, day_bars, "open"
        )
        signal_date = pd.NaT
        portfolio_rebalance = _RebalanceResult(0.0, 0.0, 0, 0)
        if date in schedule:
            signal_date, portfolio_targets, benchmark_targets = schedule[date]
            portfolio_rebalance = _rebalance_account(
                "portfolio",
                portfolio_state,
                portfolio_targets,
                day_bars,
                portfolio_open_values,
                portfolio_open_nav,
                one_way_cost_rate,
                date,
                signal_date,
                trade_records,
            )
            _rebalance_account(
                "benchmark",
                benchmark_state,
                benchmark_targets,
                day_bars,
                benchmark_open_values,
                benchmark_open_nav,
                one_way_cost_rate,
                date,
                signal_date,
                trade_records,
            )
            _record_holdings(
                holding_records,
                "portfolio",
                portfolio_state,
                portfolio_targets,
                day_bars,
                date,
                signal_date,
            )
            _record_holdings(
                holding_records,
                "benchmark",
                benchmark_state,
                benchmark_targets,
                day_bars,
                date,
                signal_date,
            )

        portfolio_nav, _, stale_count = _mark_positions(portfolio_state, day_bars, "close")
        benchmark_nav, _, _ = _mark_positions(benchmark_state, day_bars, "close")
        _update_last_closes(portfolio_state, day_bars)
        _update_last_closes(benchmark_state, day_bars)
        portfolio_return = portfolio_nav / previous_portfolio_nav - 1
        benchmark_return = benchmark_nav / previous_benchmark_nav - 1
        daily_records.append(
            {
                "date": date,
                "portfolio_nav": portfolio_nav,
                "portfolio_return": portfolio_return,
                "benchmark_nav": benchmark_nav,
                "benchmark_return": benchmark_return,
                "excess_return": portfolio_return - benchmark_return,
                "cash_weight": portfolio_state.cash / portfolio_nav
                if portfolio_nav > 0
                else np.nan,
                "holding_count": len(portfolio_state.shares),
                "turnover": portfolio_rebalance.turnover,
                "transaction_cost": portfolio_rebalance.transaction_cost,
                "is_rebalance_date": date in schedule,
                "signal_date": signal_date,
                "blocked_buy_count": portfolio_rebalance.blocked_buy_count,
                "blocked_sell_count": portfolio_rebalance.blocked_sell_count,
                "stale_holding_count": stale_count,
            }
        )
        previous_portfolio_nav = portfolio_nav
        previous_benchmark_nav = benchmark_nav

    return ContinuousBacktestResult(
        daily=pd.DataFrame(daily_records, columns=CONTINUOUS_BACKTEST_COLUMNS),
        trades=pd.DataFrame(trade_records, columns=TRADE_COLUMNS),
        holdings=pd.DataFrame(holding_records, columns=HOLDING_COLUMNS),
    )


def summarize_continuous_backtest(
    backtest: pd.DataFrame,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    # 汇总连续日净值的收益、风险、成本和持仓状态。
    columns = [
        "observation_count",
        "rebalance_count",
        "portfolio_total_return",
        "benchmark_total_return",
        "excess_total_return",
        "portfolio_annualized_return",
        "benchmark_annualized_return",
        "portfolio_annualized_volatility",
        "portfolio_max_drawdown",
        "mean_turnover",
        "total_transaction_cost",
        "mean_cash_weight",
        "stale_valuation_days",
    ]
    if backtest.empty:
        return pd.DataFrame(columns=columns)
    require_positive(periods_per_year, "年化周期数")
    require_columns(
        backtest,
        (
            "date",
            "portfolio_nav",
            "portfolio_return",
            "benchmark_nav",
            "benchmark_return",
            "turnover",
            "transaction_cost",
            "cash_weight",
            "is_rebalance_date",
            "stale_holding_count",
        ),
        "连续回测数据",
    )
    ordered = backtest.copy()
    ordered["date"] = normalize_required_trade_dates(ordered["date"], "连续回测数据")
    ordered = ordered.sort_values("date").reset_index(drop=True)
    require_unique_rows(ordered, ("date",), "连续回测数据")
    numeric_columns = [
        "portfolio_nav",
        "portfolio_return",
        "benchmark_nav",
        "benchmark_return",
        "turnover",
        "transaction_cost",
        "cash_weight",
        "stale_holding_count",
    ]
    numeric = ordered[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric).all().all():
        raise ValueError("连续回测摘要输入必须全部是有限数值。")
    if numeric[["portfolio_nav", "benchmark_nav"]].le(0).any().any():
        raise ValueError("连续回测净值必须为正数。")
    ordered[numeric_columns] = numeric
    ordered["is_rebalance_date"] = normalize_boolean_values(
        ordered["is_rebalance_date"],
        "连续回测调仓标记",
    )

    observations = len(ordered)
    annualization = periods_per_year / observations
    portfolio_total = ordered["portfolio_nav"].iloc[-1] - 1
    benchmark_total = ordered["benchmark_nav"].iloc[-1] - 1
    nav_with_initial = pd.concat(
        [pd.Series([1.0]), ordered["portfolio_nav"]],
        ignore_index=True,
    )
    drawdown = nav_with_initial / nav_with_initial.cummax() - 1
    rebalance_rows = ordered.loc[ordered["is_rebalance_date"]]
    return pd.DataFrame(
        [
            {
                "observation_count": observations,
                "rebalance_count": len(rebalance_rows),
                "portfolio_total_return": portfolio_total,
                "benchmark_total_return": benchmark_total,
                "excess_total_return": portfolio_total - benchmark_total,
                "portfolio_annualized_return": ordered["portfolio_nav"].iloc[-1] ** annualization
                - 1,
                "benchmark_annualized_return": ordered["benchmark_nav"].iloc[-1] ** annualization
                - 1,
                "portfolio_annualized_volatility": ordered["portfolio_return"].std(ddof=0)
                * np.sqrt(periods_per_year),
                "portfolio_max_drawdown": drawdown.min(),
                "mean_turnover": rebalance_rows["turnover"].mean(),
                "total_transaction_cost": ordered["transaction_cost"].sum(),
                "mean_cash_weight": ordered["cash_weight"].mean(),
                "stale_valuation_days": int(ordered["stale_holding_count"].gt(0).sum()),
            }
        ]
    )
