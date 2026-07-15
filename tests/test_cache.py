from pathlib import Path

import pandas as pd

from quanters_gate.cache import cache_daily_bar_batch, load_cached_daily_bars


class CacheClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        price_type: str,
    ) -> pd.DataFrame:
        self.calls += 1
        return pd.DataFrame(
            {
                "date": [start_date, end_date],
                "symbol": [symbol, symbol],
                "price_type": [price_type, price_type],
            }
        )


def test_cache_skips_histories_with_matching_coverage(tmp_path: Path) -> None:
    client = CacheClient()
    first = cache_daily_bar_batch(
        ["000001", "000002"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        2,
    )
    second = cache_daily_bar_batch(
        ["000001", "000002"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        2,
    )
    loaded = load_cached_daily_bars(tmp_path, ["000001", "000002"])

    assert first["fetched"] == 2
    assert second["fetched"] == 0
    assert client.calls == 2
    assert len(loaded) == 4
    assert loaded.loc[0, "symbol"] == "000001"


def test_cache_refetches_when_requested_start_expands(tmp_path: Path) -> None:
    client = CacheClient()
    cache_daily_bar_batch(
        ["000001"],
        "2024-01-10",
        "2024-01-31",
        tmp_path,
        client,
        1,
    )
    progress = cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        1,
    )

    assert progress["fetched"] == 1
    assert client.calls == 2


def test_cache_refetches_when_csv_price_type_disagrees_with_metadata(tmp_path: Path) -> None:
    client = CacheClient()
    cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        1,
    )
    cache_path = tmp_path / "000001.csv"
    cached = pd.read_csv(cache_path, dtype={"symbol": "string"})
    cached["price_type"] = "ex_rights"
    cached.to_csv(cache_path, index=False)

    progress = cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        1,
    )

    assert progress["fetched"] == 1
    assert client.calls == 2


def test_cache_batch_continues_after_one_symbol_fails(
    tmp_path: Path,
    capsys,
) -> None:
    class PartiallyFailingClient(CacheClient):
        def fetch_daily_bars(
            self,
            symbol: str,
            start_date: str,
            end_date: str,
            price_type: str,
        ) -> pd.DataFrame:
            if symbol == "000001":
                raise RuntimeError("模拟接口失败")
            return super().fetch_daily_bars(symbol, start_date, end_date, price_type)

    progress = cache_daily_bar_batch(
        ["000001", "000002"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        PartiallyFailingClient(),
        2,
    )

    assert progress == {"total": 2, "cached": 0, "fetched": 1, "failed": 1, "remaining": 1}
    assert not (tmp_path / "000001.csv").exists()
    assert (tmp_path / "000002.csv").exists()
    assert "本批已继续处理其他股票" in capsys.readouterr().out
