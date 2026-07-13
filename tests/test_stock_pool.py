import unittest

import pandas as pd

from src.stock_pool import build_index_stock_pool_history, monthly_rebalance_dates


class StockPoolTests(unittest.TestCase):
    def test_monthly_rebalance_dates_use_last_real_trading_day(self) -> None:
        dates = pd.Series(["2024-01-30", "2024-01-31", "2024-02-28", "2024-02-29"])

        result = monthly_rebalance_dates(dates)

        self.assertEqual(result, [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")])

    def test_history_combines_snapshots_with_date_labels(self) -> None:
        snapshot = pd.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "name": ["A", "B"],
                "market": ["a", "a"],
                "area_code": ["cn", "cn"],
            }
        )
        history = build_index_stock_pool_history(
            {
                pd.Timestamp("2024-01-31"): snapshot,
                pd.Timestamp("2024-02-29"): snapshot,
            },
            "000300",
        )

        self.assertEqual(len(history), 4)
        self.assertEqual(history["as_of_date"].nunique(), 2)
