import unittest

import pandas as pd

from src.data_cleaner import build_cleaning_summary, clean_daily_bars


class DailyBarCleanerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_data = pd.DataFrame(
            [
                {"date": "2024-01-02", "symbol": "000001", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000},
                {"date": "2024-01-02", "symbol": "000001", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 110, "amount": 1210},
                {"date": "2024-01-03", "symbol": "000001", "open": 11, "high": 10, "low": 9, "close": 10, "volume": 100, "amount": 1000},
                {"date": "2024-01-04", "symbol": "000001", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 0, "amount": 0},
                {"date": "invalid", "symbol": "000002", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000},
            ]
        )

    def test_cleaner_keeps_latest_duplicate_and_marks_suspension(self) -> None:
        cleaned = clean_daily_bars(self.raw_data)

        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned.loc[cleaned["date"] == pd.Timestamp("2024-01-02"), "close"].item(), 11)
        self.assertFalse(cleaned.loc[cleaned["date"] == pd.Timestamp("2024-01-04"), "is_tradable"].item())

    def test_cleaning_summary_reports_removed_rows(self) -> None:
        cleaned = clean_daily_bars(self.raw_data)
        summary = build_cleaning_summary(self.raw_data, cleaned)

        self.assertEqual(summary.loc[0, "removed_rows"], 3)
        self.assertEqual(summary.loc[0, "untradable_rows"], 1)

    def test_cleaner_normalizes_timezone_to_shanghai_trade_date(self) -> None:
        raw = self.raw_data.iloc[[0]].copy()
        raw.loc[:, "date"] = "2024-01-02T00:00:00+08:00"

        cleaned = clean_daily_bars(raw)

        self.assertEqual(cleaned.loc[0, "date"], pd.Timestamp("2024-01-02"))


if __name__ == "__main__":
    unittest.main()
