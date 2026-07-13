import unittest

from src.data_fetcher import LixingerClient


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
