import pandas as pd
import pytest

from quanters_gate.backtest.continuous import (
    run_continuous_top_n_backtest,
    summarize_continuous_backtest,
)


def _signals() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for date, scores in (
        ("2024-01-31", (2.0, 1.0)),
        ("2024-02-29", (1.0, 2.0)),
        ("2024-03-29", (2.0, 1.0)),
    ):
        for symbol, score in zip(("000001", "000002"), scores, strict=True):
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "score": score,
                    "eligible_on_signal_date": True,
                }
            )
    return pd.DataFrame(records)


def _market_bars() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2024-01-31",
            "2024-02-01",
            "2024-02-02",
            "2024-02-29",
            "2024-03-01",
            "2024-03-04",
            "2024-03-29",
        ]
    )
    records: list[dict[str, object]] = []
    prices = {
        "000001": [(10, 10), (10, 11), (11, 12), (12, 12), (12, 12), (12, 12), (12, 12)],
        "000002": [(20, 20), (20, 20), (20, 20), (20, 20), (20, 22), (22, 22), (22, 22)],
    }
    for symbol, symbol_prices in prices.items():
        for date, (open_price, close_price) in zip(dates, symbol_prices, strict=True):
            records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": open_price,
                    "close": close_price,
                    "is_tradable": True,
                    "price_type": "lxr_fc_rights",
                }
            )
    return pd.DataFrame(records)


def test_continuous_backtest_trades_next_open_and_values_daily() -> None:
    result = run_continuous_top_n_backtest(
        _signals(),
        _market_bars(),
        {"score": 1.0},
        top_n=1,
    )

    daily = result.daily.set_index("date")
    assert daily.index.min() == pd.Timestamp("2024-02-01")
    assert daily.loc[pd.Timestamp("2024-02-01"), "portfolio_nav"] == pytest.approx(1.1)
    assert daily.loc[pd.Timestamp("2024-02-02"), "portfolio_nav"] == pytest.approx(1.2)
    assert daily.loc[pd.Timestamp("2024-03-01"), "portfolio_nav"] == pytest.approx(1.32)
    portfolio_trades = result.trades.loc[result.trades["account"].eq("portfolio")].reset_index(
        drop=True
    )
    assert portfolio_trades["side"].tolist() == [
        "buy",
        "sell",
        "buy",
    ]
    assert portfolio_trades.loc[0, "date"] == pd.Timestamp("2024-02-01")
    assert portfolio_trades.loc[1, "date"] == pd.Timestamp("2024-03-01")


def test_continuous_backtest_deducts_both_sides_of_transaction_costs() -> None:
    result = run_continuous_top_n_backtest(
        _signals(),
        _market_bars(),
        {"score": 1.0},
        top_n=1,
        one_way_cost_rate=0.01,
    )

    portfolio_trades = result.trades.loc[result.trades["account"].eq("portfolio")]
    first_day = result.daily.iloc[0]
    assert portfolio_trades.iloc[0]["transaction_cost"] > 0
    assert first_day["portfolio_nav"] < 1.1
    march_cost = portfolio_trades.loc[
        portfolio_trades["date"].eq(pd.Timestamp("2024-03-01")), "transaction_cost"
    ]
    assert len(march_cost) == 2
    assert march_cost.sum() > 0


def test_continuous_backtest_freezes_an_untradable_holding() -> None:
    bars = _market_bars()
    blocked = bars["date"].eq(pd.Timestamp("2024-03-01")) & bars["symbol"].eq("000001")
    bars.loc[blocked, "is_tradable"] = False

    result = run_continuous_top_n_backtest(
        _signals(),
        bars,
        {"score": 1.0},
        top_n=1,
    )

    march = result.daily.loc[result.daily["date"].eq(pd.Timestamp("2024-03-01"))].iloc[0]
    assert march["blocked_sell_count"] == 1
    assert march["holding_count"] == 1
    portfolio_holdings = result.holdings.loc[
        result.holdings["account"].eq("portfolio")
        & result.holdings["date"].eq(pd.Timestamp("2024-03-01"))
    ]
    assert portfolio_holdings["symbol"].tolist() == ["000001"]
    assert portfolio_holdings["is_selected"].tolist() == [False]


def test_continuous_backtest_keeps_a_removed_stock_until_the_next_trade_date() -> None:
    signals = _signals()
    removed = signals["date"].eq("2024-02-29") & signals["symbol"].eq("000001")
    signals.loc[removed, "eligible_on_signal_date"] = False
    signals.loc[signals["date"].eq("2024-02-29"), "score"] = [3.0, 1.0]

    result = run_continuous_top_n_backtest(
        signals,
        _market_bars(),
        {"score": 1.0},
        top_n=1,
    )

    portfolio_trades = result.trades.loc[result.trades["account"].eq("portfolio")]
    removed_sales = portfolio_trades.loc[
        portfolio_trades["symbol"].eq("000001") & portfolio_trades["side"].eq("sell")
    ]
    assert removed_sales["date"].tolist() == [pd.Timestamp("2024-03-01")]
    assert (
        result.daily.loc[
            result.daily["date"].eq(pd.Timestamp("2024-02-29")), "holding_count"
        ].item()
        == 1
    )


def test_continuous_backtest_marks_stale_valuation_without_trading() -> None:
    bars = _market_bars()
    missing = bars["date"].eq(pd.Timestamp("2024-02-02")) & bars["symbol"].eq("000001")
    bars = bars.loc[~missing].copy()

    result = run_continuous_top_n_backtest(
        _signals(),
        bars,
        {"score": 1.0},
        top_n=1,
    )

    stale_day = result.daily.loc[result.daily["date"].eq(pd.Timestamp("2024-02-02"))].iloc[0]
    assert stale_day["stale_holding_count"] == 1
    assert stale_day["portfolio_nav"] == pytest.approx(1.1)


def test_continuous_backtest_rejects_unadjusted_research_prices() -> None:
    bars = _market_bars()
    bars["price_type"] = "ex_rights"

    with pytest.raises(ValueError, match="lxr_fc_rights"):
        run_continuous_top_n_backtest(
            _signals(),
            bars,
            {"score": 1.0},
            top_n=1,
        )


def test_continuous_summary_uses_daily_nav_and_initial_drawdown() -> None:
    daily = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "portfolio_nav": [0.9, 0.99],
            "portfolio_return": [-0.1, 0.1],
            "benchmark_nav": [1.0, 1.0],
            "benchmark_return": [0.0, 0.0],
            "turnover": [1.0, 0.0],
            "transaction_cost": [0.001, 0.0],
            "cash_weight": [0.0, 0.0],
            "is_rebalance_date": [True, False],
            "stale_holding_count": [0, 1],
        }
    )

    summary = summarize_continuous_backtest(daily)

    assert summary.loc[0, "portfolio_total_return"] == pytest.approx(-0.01)
    assert summary.loc[0, "portfolio_max_drawdown"] == pytest.approx(-0.1)
    assert summary.loc[0, "rebalance_count"] == 1
    assert summary.loc[0, "stale_valuation_days"] == 1
