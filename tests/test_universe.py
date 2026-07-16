import pandas as pd
import pytest

from quanters_gate.data.universe import (
    ELIGIBILITY_COLUMN,
    attach_membership_eligibility,
    build_index_stock_pool,
    build_index_stock_pool_history,
    monthly_rebalance_dates,
    normalize_symbols,
    select_eligible_signals,
)
from quanters_gate.research.returns import add_forward_returns


def test_normalize_symbols_deduplicates_in_input_order() -> None:
    assert normalize_symbols(["000002", "000001", "000002"]) == ["000002", "000001"]


def test_monthly_rebalance_dates_use_last_real_trading_day() -> None:
    dates = pd.Series(["2024-01-30", "2024-01-31", "2024-02-28", "2024-02-29"])

    assert monthly_rebalance_dates(dates) == [
        pd.Timestamp("2024-01-31"),
        pd.Timestamp("2024-02-29"),
    ]


def test_monthly_rebalance_dates_reject_invalid_dates() -> None:
    with pytest.raises(ValueError, match="无效交易日期"):
        monthly_rebalance_dates(pd.Series(["2024-01-31", "无效日期"]))


def test_history_combines_snapshots_and_handles_duplicates() -> None:
    snapshot = pd.DataFrame(
        {
            "symbol": ["000001", "000001", "000002"],
            "name": ["旧名称", "新名称", "股票乙"],
            "market": ["a", "a", "a"],
            "area_code": ["cn", "cn", "cn"],
        }
    )
    history = build_index_stock_pool_history(
        {
            pd.Timestamp("2024-01-31"): snapshot,
            pd.Timestamp("2024-02-29"): snapshot,
        },
        "000300",
    )

    assert len(history) == 4
    assert history["as_of_date"].nunique() == 2
    assert set(history["name"]) == {"新名称", "股票乙"}


def test_eligibility_keeps_all_prices_and_marks_latest_snapshot() -> None:
    market = pd.DataFrame(
        {
            "date": [
                "2024-01-30",
                "2024-01-31",
                "2024-02-01",
                "2024-02-01",
                "2024-03-01",
                "2024-03-01",
            ],
            "symbol": ["000001", "000001", "000001", "000002", "000001", "000002"],
        }
    )
    history = pd.DataFrame(
        {
            "as_of_date": ["2024-01-31", "2024-02-29"],
            "symbol": ["000001", "000002"],
        }
    )

    panel = attach_membership_eligibility(market, history)
    eligible = panel.loc[panel[ELIGIBILITY_COLUMN], ["date", "symbol"]]

    assert len(panel) == len(market)
    assert eligible.values.tolist() == [
        [pd.Timestamp("2024-01-31"), "000001"],
        [pd.Timestamp("2024-02-01"), "000001"],
        [pd.Timestamp("2024-03-01"), "000002"],
    ]


def test_forward_return_uses_prices_after_index_exit() -> None:
    market = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "symbol": ["000001"] * 4,
            "close": [10.0, 11.0, 12.0, 13.0],
        }
    )
    membership = pd.DataFrame(
        {
            "as_of_date": ["2024-01-01", "2024-01-03"],
            "symbol": ["000001", "000002"],
        }
    )

    panel = attach_membership_eligibility(market, membership)
    panel = add_forward_returns(panel, horizon=2)
    signal_rows = select_eligible_signals(panel)

    january_second = signal_rows.loc[signal_rows["date"] == pd.Timestamp("2024-01-02")]
    assert january_second["forward_return_2d"].item() == 13 / 11 - 1


def test_signal_eligibility_accepts_boolean_text_without_treating_false_as_true() -> None:
    panel = pd.DataFrame(
        {
            "eligible_on_signal_date": ["False", "True", None, "0", "1"],
            "symbol": ["000001", "000002", "000003", "000004", "000005"],
        }
    )

    selected = select_eligible_signals(panel)

    assert selected["symbol"].tolist() == ["000002", "000005"]


def test_history_rejects_empty_snapshot() -> None:
    empty = pd.DataFrame(columns=["symbol", "name", "market", "area_code"])

    with pytest.raises(ValueError, match="快照为空"):
        build_index_stock_pool_history({pd.Timestamp("2024-01-31"): empty}, "000300")


def test_eligibility_rejects_invalid_market_dates() -> None:
    market = pd.DataFrame({"date": ["invalid"], "symbol": ["000001"]})
    membership = pd.DataFrame({"as_of_date": ["2024-01-31"], "symbol": ["000001"]})

    with pytest.raises(ValueError, match="无效交易日期"):
        attach_membership_eligibility(market, membership)


def test_stock_pool_rejects_missing_identity_fields() -> None:
    constituents = pd.DataFrame(
        {
            "symbol": ["000001"],
            "name": [None],
            "market": ["a"],
            "area_code": ["cn"],
        }
    )

    with pytest.raises(ValueError, match="缺失"):
        build_index_stock_pool(constituents, "000300", "2024-01-31")


def test_eligibility_rejects_duplicate_membership_records() -> None:
    market = pd.DataFrame({"date": ["2024-01-31"], "symbol": ["000001"]})
    membership = pd.DataFrame(
        {
            "as_of_date": ["2024-01-31", "2024-01-31"],
            "symbol": ["000001", "000001"],
        }
    )

    with pytest.raises(ValueError, match="重复记录"):
        attach_membership_eligibility(market, membership)


def test_eligibility_rejects_duplicate_market_records() -> None:
    market = pd.DataFrame(
        {
            "date": ["2024-01-31", "2024-01-31"],
            "symbol": ["000001", "000001"],
        }
    )
    membership = pd.DataFrame({"as_of_date": ["2024-01-31"], "symbol": ["000001"]})

    with pytest.raises(ValueError, match="重复记录"):
        attach_membership_eligibility(market, membership)
