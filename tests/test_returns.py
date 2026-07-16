import pandas as pd

from quanters_gate.research.returns import add_forward_returns


def test_forward_return_does_not_bridge_a_missing_market_date() -> None:
    dates = pd.date_range("2024-01-01", periods=4, freq="B")
    complete = pd.DataFrame(
        {
            "date": dates,
            "symbol": ["000001"] * 4,
            "close": [10.0, 11.0, 12.0, 13.0],
        }
    )
    incomplete = pd.DataFrame(
        {
            "date": [dates[0], dates[2], dates[3]],
            "symbol": ["000002"] * 3,
            "close": [20.0, 22.0, 23.0],
        }
    )

    result = add_forward_returns(pd.concat([complete, incomplete], ignore_index=True), horizon=1)
    first_incomplete = result.loc[result["symbol"] == "000002"].iloc[0]

    assert pd.isna(first_incomplete["forward_return_1d"])
