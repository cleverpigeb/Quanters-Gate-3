import pandas as pd
import pytest

from quanters_gate.research.factors import calculate_price_factors


@pytest.fixture
def price_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=65, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "000001",
            "close": [100 + day for day in range(65)],
            "amount": [1_000_000 + day * 1_000 for day in range(65)],
            "turnover": [0.01 + day * 0.0001 for day in range(65)],
        }
    )


def test_calculator_requires_full_lookback_window(price_data: pd.DataFrame) -> None:
    factors = calculate_price_factors(price_data)

    assert factors.loc[:19, "momentum_20d"].isna().all()
    assert factors.loc[20, "momentum_20d"] == pytest.approx(0.2)
    assert factors.loc[60, "momentum_60d"] == pytest.approx(0.6)
    assert factors.loc[20, "reversal_5d"] == pytest.approx(-(120 / 115 - 1))
    assert pd.notna(factors.loc[20, "volatility_20d"])
    assert pd.notna(factors.loc[20, "turnover_proxy_20d"])
    assert pd.notna(factors.loc[20, "amihud_20d"])
    assert pd.notna(factors.loc[20, "max_return_20d"])
    assert pd.notna(factors.loc[24, "turnover_surprise_5d_20d"])


def test_calculator_rejects_incomplete_input(price_data: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="amount"):
        calculate_price_factors(price_data.drop(columns="amount"))


def test_calculator_does_not_bridge_a_missing_market_date(price_data: pd.DataFrame) -> None:
    complete = price_data.copy()
    incomplete = price_data.copy()
    incomplete["symbol"] = "000002"
    incomplete = incomplete.drop(index=60)
    panel = pd.concat([complete, incomplete], ignore_index=True)

    factors = calculate_price_factors(panel)
    last_incomplete = factors.loc[factors["symbol"] == "000002"].iloc[-1]

    assert pd.isna(last_incomplete["momentum_20d"])
    assert pd.isna(last_incomplete["volatility_20d"])
    assert pd.isna(last_incomplete["turnover_proxy_20d"])
    assert pd.isna(last_incomplete["amihud_20d"])
    assert pd.isna(last_incomplete["max_return_20d"])
    assert pd.isna(last_incomplete["turnover_surprise_5d_20d"])
