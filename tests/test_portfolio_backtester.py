import unittest

import pandas as pd

from src.portfolio_backtester import run_monthly_top_n_backtest, summarize_backtest


class PortfolioBacktesterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = pd.DataFrame(
            [
                {"date": "2024-01-31", "symbol": "000001", "score": 2.0, "forward_return_20d": 0.10},
                {"date": "2024-01-31", "symbol": "000002", "score": 1.0, "forward_return_20d": 0.00},
                {"date": "2024-02-29", "symbol": "000001", "score": 2.0, "forward_return_20d": 0.02},
                {"date": "2024-02-29", "symbol": "000002", "score": 1.0, "forward_return_20d": 0.04},
                {"date": "2024-03-29", "symbol": "000001", "score": 1.0, "forward_return_20d": -0.02},
                {"date": "2024-03-29", "symbol": "000002", "score": 2.0, "forward_return_20d": -0.03},
            ]
        )

    def test_monthly_top_n_selects_highest_score_and_tracks_turnover(self) -> None:
        result = run_monthly_top_n_backtest(self.panel, {"score": 1.0}, horizon=20, top_n=1)

        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result.loc[0, "portfolio_return"], 0.10)
        self.assertAlmostEqual(result.loc[1, "turnover"], 0.0)
        self.assertAlmostEqual(result.loc[2, "turnover"], 1.0)
        self.assertAlmostEqual(result.loc[0, "benchmark_return"], 0.05)

    def test_summary_contains_compound_returns_and_drawdown(self) -> None:
        backtest = run_monthly_top_n_backtest(self.panel, {"score": 1.0}, horizon=20, top_n=1)
        summary = summarize_backtest(backtest)

        self.assertEqual(summary.loc[0, "observation_count"], 3)
        self.assertAlmostEqual(summary.loc[0, "portfolio_total_return"], 1.10 * 1.02 * 0.97 - 1)
        self.assertLess(summary.loc[0, "portfolio_max_drawdown"], 0)

    def test_backtest_rejects_empty_factor_weights(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            run_monthly_top_n_backtest(self.panel, {}, horizon=20, top_n=1)


if __name__ == "__main__":
    unittest.main()
