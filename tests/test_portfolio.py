import pandas as pd
import pytest

from quanters_gate.backtest.portfolio import run_monthly_top_n_backtest, summarize_backtest


@pytest.fixture
def portfolio_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2024-01-31",
                "symbol": "000001",
                "score": 2.0,
                "forward_return_20d": 0.10,
            },
            {
                "date": "2024-01-31",
                "symbol": "000002",
                "score": 1.0,
                "forward_return_20d": 0.00,
            },
            {
                "date": "2024-02-29",
                "symbol": "000001",
                "score": 2.0,
                "forward_return_20d": 0.02,
            },
            {
                "date": "2024-02-29",
                "symbol": "000002",
                "score": 1.0,
                "forward_return_20d": 0.04,
            },
            {
                "date": "2024-03-29",
                "symbol": "000001",
                "score": 1.0,
                "forward_return_20d": -0.02,
            },
            {
                "date": "2024-03-29",
                "symbol": "000002",
                "score": 2.0,
                "forward_return_20d": -0.03,
            },
        ]
    )


def test_monthly_top_n_selects_highest_score_and_tracks_turnover(
    portfolio_panel: pd.DataFrame,
) -> None:
    result = run_monthly_top_n_backtest(
        portfolio_panel,
        {"score": 1.0},
        horizon=20,
        top_n=1,
    )

    assert len(result) == 3
    assert result.loc[0, "portfolio_return"] == pytest.approx(0.10)
    assert result.loc[1, "turnover"] == pytest.approx(0.0)
    assert result.loc[2, "turnover"] == pytest.approx(1.0)
    assert result.loc[0, "benchmark_return"] == pytest.approx(0.05)


def test_backtest_respects_signal_eligibility(portfolio_panel: pd.DataFrame) -> None:
    panel = portfolio_panel.iloc[:2].copy()
    panel["eligible_on_signal_date"] = [False, True]

    result = run_monthly_top_n_backtest(panel, {"score": 1.0}, horizon=20, top_n=1)

    assert result.loc[0, "portfolio_return"] == pytest.approx(0.0)


def test_summary_contains_compound_returns_and_drawdown(portfolio_panel: pd.DataFrame) -> None:
    backtest = run_monthly_top_n_backtest(
        portfolio_panel,
        {"score": 1.0},
        horizon=20,
        top_n=1,
    )
    summary = summarize_backtest(backtest)

    assert summary.loc[0, "observation_count"] == 3
    assert summary.loc[0, "portfolio_total_return"] == pytest.approx(1.10 * 1.02 * 0.97 - 1)
    assert summary.loc[0, "portfolio_max_drawdown"] < 0


def test_summary_drawdown_includes_the_initial_nav() -> None:
    backtest = pd.DataFrame(
        {
            "date": ["2024-01-31"],
            "portfolio_return": [-0.10],
            "benchmark_return": [0.0],
            "turnover": [1.0],
        }
    )

    summary = summarize_backtest(backtest)

    assert summary.loc[0, "portfolio_max_drawdown"] == pytest.approx(-0.10)


def test_backtest_rejects_empty_factor_weights(portfolio_panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="不能为空"):
        run_monthly_top_n_backtest(portfolio_panel, {}, horizon=20, top_n=1)


def test_backtest_rejects_all_zero_factor_weights(portfolio_panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="不能全部为零"):
        run_monthly_top_n_backtest(
            portfolio_panel,
            {"score": 0.0},
            horizon=20,
            top_n=1,
        )


def test_backtest_ignores_zero_weight_factor_columns(portfolio_panel: pd.DataFrame) -> None:
    result = run_monthly_top_n_backtest(
        portfolio_panel,
        {"score": 1.0, "unused_factor": 0.0},
        horizon=20,
        top_n=1,
    )

    assert len(result) == 3


def test_turnover_handles_a_change_in_holding_count() -> None:
    panel = pd.DataFrame(
        [
            {
                "date": "2024-01-31",
                "symbol": "000001",
                "score": 2.0,
                "forward_return_20d": 0.01,
            },
            {
                "date": "2024-01-31",
                "symbol": "000002",
                "score": 1.0,
                "forward_return_20d": None,
            },
            {
                "date": "2024-02-29",
                "symbol": "000001",
                "score": 2.0,
                "forward_return_20d": 0.01,
            },
            {
                "date": "2024-02-29",
                "symbol": "000002",
                "score": 1.0,
                "forward_return_20d": 0.01,
            },
        ]
    )

    result = run_monthly_top_n_backtest(panel, {"score": 1.0}, horizon=20, top_n=2)

    assert result.loc[1, "turnover"] == pytest.approx(0.5)


def test_backtest_rejects_duplicate_signal_rows(portfolio_panel: pd.DataFrame) -> None:
    duplicated = pd.concat([portfolio_panel, portfolio_panel.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="重复记录"):
        run_monthly_top_n_backtest(duplicated, {"score": 1.0}, horizon=20, top_n=1)


def test_backtest_does_not_treat_false_text_as_tradable(
    portfolio_panel: pd.DataFrame,
) -> None:
    panel = portfolio_panel.iloc[:2].copy()
    panel["is_tradable"] = ["False", "True"]

    result = run_monthly_top_n_backtest(panel, {"score": 1.0}, horizon=20, top_n=1)

    assert result.loc[0, "portfolio_return"] == pytest.approx(0.0)
