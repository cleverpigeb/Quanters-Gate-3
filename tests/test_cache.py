import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import quanters_gate.data.cache as cache_module
from quanters_gate.data.cache import (
    cache_daily_bar_batch,
    fetch_universe_daily_bars,
    load_cached_daily_bars,
)
from quanters_gate.storage import calculate_sha256


class CacheClient:
    provider_name = "lixinger"

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


def test_fetch_universe_daily_bars_uses_injected_provider() -> None:
    provider = CacheClient()

    bars = fetch_universe_daily_bars(
        ["000001", "000002"],
        "2024-01-01",
        "2024-01-31",
        provider,
    )

    assert provider.calls == 2
    assert bars["symbol"].tolist() == ["000001", "000001", "000002", "000002"]


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


def test_cache_metadata_records_content_identity(tmp_path: Path) -> None:
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
    metadata = json.loads((tmp_path / "000001.meta.json").read_text(encoding="utf-8"))

    assert metadata["schema_version"] == 1
    assert metadata["provider"] == "lixinger"
    assert metadata["row_count"] == 2
    assert metadata["content_sha256"] == calculate_sha256(cache_path)
    assert datetime.fromisoformat(metadata["built_at"]).tzinfo is not None


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


def test_cache_refetches_when_provider_changes(tmp_path: Path) -> None:
    first_provider = CacheClient()
    cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        first_provider,
        1,
    )

    class OfflineProvider(CacheClient):
        provider_name = "offline"

    second_provider = OfflineProvider()
    progress = cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        second_provider,
        1,
    )
    metadata = json.loads((tmp_path / "000001.meta.json").read_text(encoding="utf-8"))

    assert progress["fetched"] == 1
    assert second_provider.calls == 1
    assert metadata["provider"] == "offline"


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


def test_cache_refetches_when_csv_content_hash_changes(tmp_path: Path) -> None:
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
    cached.loc[0, "date"] = "2024-01-02"
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


def test_cache_refetches_after_metadata_commit_failure(tmp_path: Path, monkeypatch) -> None:
    client = CacheClient()
    original_writer = cache_module.atomic_write_json

    def fail_metadata_commit(*args, **kwargs) -> None:
        raise OSError("模拟元数据提交失败")

    monkeypatch.setattr(cache_module, "atomic_write_json", fail_metadata_commit)
    failed = cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        1,
    )
    monkeypatch.setattr(cache_module, "atomic_write_json", original_writer)
    retried = cache_daily_bar_batch(
        ["000001"],
        "2024-01-01",
        "2024-01-31",
        tmp_path,
        client,
        1,
    )

    assert failed["failed"] == 1
    assert (tmp_path / "000001.csv").exists()
    assert retried["fetched"] == 1
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
