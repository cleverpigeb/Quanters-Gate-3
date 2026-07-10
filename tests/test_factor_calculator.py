import unittest

import pandas as pd

from src.factor_calculator import calculate_price_factors


class FactorCalculatorTests(unittest.TestCase):
    def setUp(self) -> None:
        dates = pd.date_range("2024-01-01", periods=25, freq="B")
        self.data = pd.DataFrame(
            {
                "date": dates,
                "symbol": "000001",
                "close": [100 + day for day in range(25)],
                "amount": [1_000_000 + day * 1_000 for day in range(25)],
            }
        )

    def test_calculator_requires_full_lookback_window(self) -> None:
        factors = calculate_price_factors(self.data)

        self.assertTrue(factors.loc[:19, "momentum_20d"].isna().all())
        self.assertAlmostEqual(factors.loc[20, "momentum_20d"], 0.2)
        self.assertAlmostEqual(factors.loc[20, "reversal_5d"], -(120 / 115 - 1))
        self.assertTrue(pd.notna(factors.loc[20, "volatility_20d"]))
        self.assertTrue(pd.notna(factors.loc[20, "turnover_proxy_20d"]))

    def test_calculator_rejects_incomplete_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "amount"):
            calculate_price_factors(self.data.drop(columns="amount"))


if __name__ == "__main__":
    unittest.main()
