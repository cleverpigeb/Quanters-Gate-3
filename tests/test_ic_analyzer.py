import unittest

import pandas as pd

from src.ic_analyzer import add_forward_returns, calculate_rank_ic, summarize_rank_ic


class ICAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
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
        self.panel = pd.DataFrame(rows)

    def test_rank_ic_uses_only_future_returns_and_respects_sampling_step(self) -> None:
        panel = add_forward_returns(self.panel, horizon=1)
        rank_ic = calculate_rank_ic(panel, ["test_factor"], horizon=1, sample_step=2)
        summary = summarize_rank_ic(rank_ic)

        self.assertEqual(len(rank_ic), 3)
        self.assertTrue((rank_ic["rank_ic"] == 1.0).all())
        self.assertEqual(summary.loc[0, "count"], 3)
        self.assertEqual(summary.loc[0, "positive_rate"], 1.0)

    def test_rank_ic_requires_forward_return_column(self) -> None:
        with self.assertRaisesRegex(ValueError, "target"):
            calculate_rank_ic(self.panel, ["test_factor"], horizon=1, sample_step=1)

    def test_empty_rank_ic_summary_has_stable_schema(self) -> None:
        summary = summarize_rank_ic(pd.DataFrame(columns=["date", "factor", "rank_ic"]))

        self.assertEqual(summary.columns.tolist()[0], "factor")
        self.assertTrue(summary.empty)


if __name__ == "__main__":
    unittest.main()
