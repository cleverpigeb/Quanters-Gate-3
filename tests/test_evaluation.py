import pandas as pd
import pytest

from quanters_gate.research.evaluation import (
    build_factor_diagnostic_summary,
    calculate_factor_rank_correlations,
    calculate_quantile_returns,
    calculate_rank_ic,
    summarize_factor_rank_correlations,
    summarize_quantile_returns,
    summarize_rank_ic,
    summarize_rank_ic_by_year,
    summarize_top_bottom_spreads,
)
from quanters_gate.research.returns import add_forward_returns


@pytest.fixture
def ic_panel() -> pd.DataFrame:
    rows = []
    for day in range(6):
        for score in range(1, 5):
            rows.append(
                {
                    "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                    "symbol": f"00000{score}",
                    "close": 100 * (1 + score * 0.01) ** day,
                    "test_factor": score,
                }
            )
    return pd.DataFrame(rows)


def test_rank_ic_uses_future_returns_and_sampling_step(ic_panel: pd.DataFrame) -> None:
    panel = add_forward_returns(ic_panel, horizon=1)
    rank_ic = calculate_rank_ic(panel, ["test_factor"], horizon=1, sample_step=2)
    summary = summarize_rank_ic(rank_ic)

    assert len(rank_ic) == 3
    assert (rank_ic["rank_ic"] == 1.0).all()
    assert summary.loc[0, "count"] == 3
    assert summary.loc[0, "positive_rate"] == 1.0


def test_empty_rank_ic_has_stable_schema() -> None:
    panel = pd.DataFrame(
        {
            "date": ["2024-01-01"],
            "symbol": ["000001"],
            "test_factor": [1.0],
            "forward_return_1d": [0.1],
        }
    )
    rank_ic = calculate_rank_ic(panel, ["test_factor"], horizon=1, sample_step=1)

    assert rank_ic.columns.tolist() == ["date", "factor", "rank_ic"]
    assert summarize_rank_ic(rank_ic).empty


def test_quantile_returns_and_top_bottom_spread() -> None:
    rows = []
    for date in ("2024-01-02", "2024-01-03"):
        for score in range(1, 6):
            rows.append(
                {
                    "date": date,
                    "symbol": f"00000{score}",
                    "test_factor": score,
                    "forward_return_1d": score * 0.01,
                }
            )
    panel = pd.DataFrame(rows)

    returns = calculate_quantile_returns(panel, ["test_factor"], 1, 5, sample_step=1)
    summary = summarize_quantile_returns(returns)
    spreads = summarize_top_bottom_spreads(summary, 5)

    assert len(returns) == 10
    assert summary.loc[summary["quantile"] == 1, "observation_count"].item() == 2
    assert spreads.loc[0, "top_bottom_spread"] == pytest.approx(0.04)


def test_quantile_evaluation_rejects_too_few_groups() -> None:
    panel = pd.DataFrame(
        {
            "date": ["2024-01-01"],
            "symbol": ["000001"],
            "test_factor": [1.0],
            "forward_return_1d": [0.1],
        }
    )

    with pytest.raises(ValueError, match="至少"):
        calculate_quantile_returns(panel, ["test_factor"], 1, 1, sample_step=1)


def test_constant_rank_ic_has_undefined_ir_instead_of_infinity() -> None:
    rank_ic = pd.DataFrame({"factor": ["test", "test"], "rank_ic": [0.5, 0.5]})

    summary = summarize_rank_ic(rank_ic)

    assert pd.isna(summary.loc[0, "ic_ir"])


def test_rank_ic_yearly_summary_keeps_year_boundaries() -> None:
    rank_ic = pd.DataFrame(
        {
            "date": ["2023-01-03", "2023-02-03", "2024-01-03", "2024-02-03"],
            "factor": ["test"] * 4,
            "rank_ic": [0.1, 0.3, -0.2, -0.4],
        }
    )

    summary = summarize_rank_ic_by_year(rank_ic)

    assert summary["year"].tolist() == [2023, 2024]
    assert summary["mean_rank_ic"].tolist() == pytest.approx([0.2, -0.3])
    assert summary["positive_rate"].tolist() == [1.0, 0.0]


def test_evaluation_rejects_overlapping_forward_windows() -> None:
    panel = pd.DataFrame(
        {
            "date": ["2024-01-01"] * 3,
            "test_factor": [1.0, 2.0, 3.0],
            "forward_return_20d": [0.01, 0.02, 0.03],
        }
    )

    with pytest.raises(ValueError, match="窗口会重叠"):
        calculate_rank_ic(panel, ["test_factor"], horizon=20, sample_step=10)


def test_evaluation_rejects_duplicate_security_dates(ic_panel: pd.DataFrame) -> None:
    panel = add_forward_returns(ic_panel, horizon=1)
    duplicated = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="重复记录"):
        calculate_rank_ic(duplicated, ["test_factor"], horizon=1, sample_step=1)


def test_factor_diagnostic_summary_combines_ic_and_quantile_evidence() -> None:
    rank_ic = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "factor": ["test_factor", "test_factor"],
            "rank_ic": [0.2, 0.4],
        }
    )
    quantile_summary = pd.DataFrame(
        {
            "factor": ["test_factor"] * 5,
            "quantile": [1, 2, 3, 4, 5],
            "mean_forward_return": [0.01, 0.02, 0.03, 0.04, 0.05],
            "observation_count": [2] * 5,
        }
    )

    result = build_factor_diagnostic_summary(rank_ic, quantile_summary, quantile_count=5)

    assert result.loc[0, "ic_count"] == 2
    assert result.loc[0, "rank_ic_t_stat"] == pytest.approx(3.0)
    assert result.loc[0, "top_bottom_spread"] == pytest.approx(0.04)
    assert result.loc[0, "quantile_monotonicity"] == pytest.approx(1.0)


def test_factor_rank_correlations_respect_signal_eligibility() -> None:
    rows = []
    for date in ("2024-01-01", "2024-01-02"):
        for value in range(1, 5):
            rows.append(
                {
                    "date": date,
                    "symbol": f"00000{value}",
                    "factor_up": value,
                    "factor_down": 5 - value,
                    "forward_return_1d": value * 0.01,
                    "eligible_on_signal_date": True,
                }
            )
    rows.append(
        {
            "date": "2024-01-01",
            "symbol": "000099",
            "factor_up": 99,
            "factor_down": 99,
            "forward_return_1d": 0.99,
            "eligible_on_signal_date": False,
        }
    )

    correlations = calculate_factor_rank_correlations(
        pd.DataFrame(rows),
        ["factor_up", "factor_down"],
        horizon=1,
    )
    summary = summarize_factor_rank_correlations(correlations)

    assert len(correlations) == 2
    assert (correlations["rank_correlation"] == -1.0).all()
    assert summary.loc[0, "mean_rank_correlation"] == pytest.approx(-1.0)
    assert summary.loc[0, "observation_count"] == 2
