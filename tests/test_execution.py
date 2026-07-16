import pandas as pd
import pytest

from quanters_gate.backtest.execution import add_next_open_execution_returns


def test_execution_return_uses_next_open_and_requires_tradable_exit() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="B")
    signals = pd.DataFrame({"date": [dates[0]], "symbol": ["000001"]})
    bars = pd.DataFrame(
        {
            "date": dates,
            "symbol": ["000001"] * 4,
            "open": [10.0, 11.0, 12.0, 13.0],
            "is_tradable": [True] * 4,
            "price_type": ["ex_rights"] * 4,
        }
    )

    result = add_next_open_execution_returns(signals, bars, horizon=2)

    assert result.loc[0, "execution_return"] == pytest.approx(13 / 11 - 1)

    bars.loc[3, "is_tradable"] = False
    blocked = add_next_open_execution_returns(signals, bars, horizon=2)
    assert pd.isna(blocked.loc[0, "execution_return"])


def test_execution_return_rejects_adjusted_prices() -> None:
    signals = pd.DataFrame({"date": ["2024-01-01"], "symbol": ["000001"]})
    bars = pd.DataFrame(
        {
            "date": ["2024-01-01"],
            "symbol": ["000001"],
            "open": [10.0],
            "is_tradable": [True],
            "price_type": ["lxr_fc_rights"],
        }
    )

    with pytest.raises(ValueError, match="ex_rights"):
        add_next_open_execution_returns(signals, bars, horizon=1)


def test_execution_return_normalizes_signal_and_bar_dates() -> None:
    signals = pd.DataFrame({"date": ["2024-01-01"], "symbol": ["000001"]})
    bars = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "symbol": ["000001"] * 3,
            "open": [10.0, 11.0, 12.0],
            "is_tradable": ["True", "True", "True"],
            "price_type": ["ex_rights"] * 3,
        }
    )

    result = add_next_open_execution_returns(signals, bars, horizon=1)

    assert result.loc[0, "date"] == pd.Timestamp("2024-01-01")
    assert result.loc[0, "execution_return"] == pytest.approx(12 / 11 - 1)


def test_execution_return_rejects_duplicate_signals() -> None:
    signals = pd.DataFrame({"date": ["2024-01-01", "2024-01-01"], "symbol": ["000001", "000001"]})
    bars = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "symbol": ["000001"] * 3,
            "open": [10.0, 11.0, 12.0],
            "is_tradable": [True] * 3,
            "price_type": ["ex_rights"] * 3,
        }
    )

    with pytest.raises(ValueError, match="重复记录"):
        add_next_open_execution_returns(signals, bars, horizon=1)
