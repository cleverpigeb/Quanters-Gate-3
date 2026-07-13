import unittest

import pandas as pd

from src.stock_pool import build_index_stock_pool_history, filter_to_membership_history, monthly_rebalance_dates


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

    def test_filter_uses_latest_available_membership_snapshot(self) -> None:
        market = pd.DataFrame(
            {
                "date": ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-01", "2024-03-01", "2024-03-01"],
                "symbol": ["000001", "000001", "000001", "000002", "000001", "000002"],
            }
        )
        history = pd.DataFrame(
            {
                "as_of_date": ["2024-01-31", "2024-02-29"],
                "symbol": ["000001", "000002"],
            }
        )

        eligible = filter_to_membership_history(market, history)

        self.assertEqual(
            eligible[["date", "symbol"]].values.tolist(),
            [
                [pd.Timestamp("2024-01-31"), "000001"],
                [pd.Timestamp("2024-02-01"), "000001"],
                [pd.Timestamp("2024-03-01"), "000002"],
            ],
        )
