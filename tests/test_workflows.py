import tomllib
from argparse import Namespace
from pathlib import Path

import pandas as pd
import pytest

from quanters_gate import workflows


class EmptySnapshotProvider:
    provider_name = "lixinger"

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def fetch_index_daily_bars(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        return pd.DataFrame({"date": ["2024-01-31"]})

    def fetch_index_constituents(self, index_code: str, as_of_date: str) -> pd.DataFrame:
        return pd.DataFrame(columns=["symbol", "name", "market", "area_code"])


def test_empty_downloaded_snapshot_is_not_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflows, "UNIVERSE_DIR", tmp_path)
    provider = EmptySnapshotProvider()
    args = Namespace(
        max_universe_snapshots=1,
        start="2024-01-01",
        end="2024-01-31",
    )

    with pytest.raises(RuntimeError, match="成分快照为空"):
        workflows.build_universe_history(args, lambda: provider)

    assert provider.closed is True
    assert not (tmp_path / "000300_monthly_snapshots" / "2024-01-31.csv").exists()


def test_resolved_run_config_records_cli_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflows, "REPORT_DIR", tmp_path)
    args = Namespace(
        run_market_history=True,
        universe_date=None,
        symbols=["000001", "600000"],
        start="2022-01-01",
        end="2024-12-31",
        horizon=10,
        max_universe_snapshots=3,
        max_market_symbols=4,
        with_preprocess=False,
        with_analysis=True,
        with_evaluation=False,
        with_backtest=False,
        with_execution_backtest=False,
    )

    config = workflows._resolve_run_config(args)
    workflows._write_run_config(config)
    saved = tomllib.loads((tmp_path / "run_config.toml").read_text(encoding="utf-8"))

    assert saved["run"]["mode"] == "historical_market"
    assert saved["run"]["with_preprocess"] is True
    assert saved["run"]["with_analysis"] is True
    assert saved["research"]["start_date"].isoformat() == "2022-01-01"
    assert saved["research"]["forward_days"] == 10
    assert saved["universe"]["symbols"] == ["000001", "600000"]
    assert saved["universe"]["market_fetch_batch_size"] == 4


def test_workflow_rejects_provider_that_disagrees_with_config() -> None:
    class MismatchedProvider(EmptySnapshotProvider):
        provider_name = "offline"

    provider = MismatchedProvider()
    args = Namespace(
        max_universe_snapshots=1,
        start="2024-01-01",
        end="2024-01-31",
    )

    with pytest.raises(ValueError, match="配置的数据源 lixinger 与注入的数据源 offline 不一致"):
        workflows.build_universe_history(args, lambda: provider)

    assert provider.closed is True
