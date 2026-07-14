import unittest

import pandas as pd

from src.execution_returns import add_next_open_execution_returns


class ExecutionReturnTests(unittest.TestCase):
    def test_uses_next_open_and_requires_tradable_entry_exit(self) -> None:
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

        self.assertAlmostEqual(result.loc[0, "execution_return"], 13 / 11 - 1)

    def test_rejects_adjusted_execution_prices(self) -> None:
        signals = pd.DataFrame({"date": ["2024-01-01"], "symbol": ["000001"]})
        bars = pd.DataFrame(
            {
                "date": ["2024-01-01"], "symbol": ["000001"], "open": [10.0],
                "is_tradable": [True], "price_type": ["lxr_fc_rights"],
            }
        )
        with self.assertRaisesRegex(ValueError, "ex_rights"):
            add_next_open_execution_returns(signals, bars, horizon=1)


if __name__ == "__main__":
    unittest.main()
