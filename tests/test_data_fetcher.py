import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from src.data_fetcher import LixingerClient, cache_daily_bar_batch, load_cached_daily_bars


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "code": 1,
            "data": [
                {"date": "2024-01-31T00:00:00+08:00", "close": 100},
                {"date": "2024-01-30T00:00:00+08:00", "close": 99},
            ],
        }


class FakeSession:
    def post(self, *args, **kwargs) -> FakeResponse:
        return FakeResponse()


class DataFetcherTests(unittest.TestCase):
    def test_index_daily_bars_returns_sorted_trading_dates(self) -> None:
        client = LixingerClient(token="test-token", session=FakeSession())

        bars = client.fetch_index_daily_bars("000300", "2024-01-01", "2024-01-31")

        self.assertEqual(len(bars), 2)
        self.assertLess(bars.loc[0, "date"], bars.loc[1, "date"])

    def test_symbol_cache_skips_histories_that_cover_requested_range(self) -> None:
        class CacheClient:
            def fetch_daily_bars(self, symbol, start_date, end_date):
                return pd.DataFrame(
                    {
                        "date": ["2024-01-01T00:00:00+08:00", "2024-01-31T00:00:00+08:00"],
                        "symbol": [symbol, symbol],
                    }
                )

        with TemporaryDirectory() as directory:
            first = cache_daily_bar_batch(["000001", "000002"], "2024-01-01", "2024-01-31", directory, CacheClient(), 2)
            second = cache_daily_bar_batch(["000001", "000002"], "2024-01-01", "2024-01-31", directory, CacheClient(), 2)
            loaded = load_cached_daily_bars(directory, ["000001", "000002"])

        self.assertEqual(first["fetched"], 2)
        self.assertEqual(second["fetched"], 0)
        self.assertEqual(len(loaded), 4)
        self.assertEqual(loaded.loc[0, "symbol"], "000001")
