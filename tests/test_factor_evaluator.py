import unittest

import pandas as pd

from src.factor_evaluator import (
    calculate_quantile_returns,
    summarize_quantile_returns,
    summarize_top_bottom_spreads,
)


class FactorEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        rows = []
        for date in ("2024-01-02", "2024-01-03"):
            for score in range(1, 6):
                rows.append(
                    {
                        "date": date,
                        "symbol": f"00000{score}",
                        "test_factor": score,
                        "forward_return_20d": score * 0.01,
                    }
                )
        self.panel = pd.DataFrame(rows)

    def test_quantile_returns_and_top_bottom_spread(self) -> None:
        returns = calculate_quantile_returns(self.panel, ["test_factor"], 20, 5)
        summary = summarize_quantile_returns(returns)
        spreads = summarize_top_bottom_spreads(summary, 5)

        self.assertEqual(len(returns), 10)
        self.assertEqual(summary.loc[summary["quantile"] == 1, "observation_count"].item(), 2)
        self.assertAlmostEqual(spreads.loc[0, "top_bottom_spread"], 0.04)

    def test_quantile_evaluation_rejects_too_few_groups(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            calculate_quantile_returns(self.panel, ["test_factor"], 20, 1)


if __name__ == "__main__":
    unittest.main()
