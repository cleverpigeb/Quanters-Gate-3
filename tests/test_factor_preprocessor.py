import unittest

import pandas as pd

from src.factor_preprocessor import build_preprocess_summary, preprocess_factors


class FactorPreprocessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = pd.DataFrame(
            {
                "date": ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
                "symbol": ["000001", "000002", "000003", "000004"] * 2,
                "test_factor": [1.0, 2.0, 3.0, 100.0, 2.0, 3.0, None, 5.0],
            }
        )

    def test_preprocessor_standardizes_each_date_and_preserves_missing_values(self) -> None:
        processed = preprocess_factors(self.panel, ["test_factor"])
        first_day = processed.loc[processed["date"] == "2024-01-02", "test_factor"]

        self.assertAlmostEqual(first_day.mean(), 0.0)
        self.assertAlmostEqual(first_day.std(ddof=0), 1.0)
        self.assertTrue(processed.loc[processed["symbol"] == "000003", "test_factor"].isna().any())

    def test_summary_reports_cross_section_coverage(self) -> None:
        summary = build_preprocess_summary(self.panel, ["test_factor"])

        self.assertEqual(summary.loc[0, "usable_date_count"], 2)
        self.assertEqual(summary.loc[0, "median_cross_section_size"], 3.5)

    def test_preprocessor_rejects_missing_identifier_columns(self) -> None:
        with self.assertRaisesRegex(ValueError, "identifier"):
            preprocess_factors(self.panel.drop(columns="date"), ["test_factor"])


if __name__ == "__main__":
    unittest.main()
