import pandas as pd
import pytest

from quanters_gate.research.factors import calculate_price_factors


@pytest.fixture
def price_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=25, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "000001",
            "close": [100 + day for day in range(25)],
            "amount": [1_000_000 + day * 1_000 for day in range(25)],
        }
    )


def test_calculator_requires_full_lookback_window(price_data: pd.DataFrame) -> None:
    factors = calculate_price_factors(price_data)

    assert factors.loc[:19, "momentum_20d"].isna().all()
    assert factors.loc[20, "momentum_20d"] == pytest.approx(0.2)
    assert factors.loc[20, "reversal_5d"] == pytest.approx(-(120 / 115 - 1))
    assert pd.notna(factors.loc[20, "volatility_20d"])
    assert pd.notna(factors.loc[20, "turnover_proxy_20d"])


def test_calculator_rejects_incomplete_input(price_data: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="amount"):
        calculate_price_factors(price_data.drop(columns="amount"))
