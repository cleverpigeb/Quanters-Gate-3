from argparse import Namespace
from pathlib import Path

import pandas as pd
import pytest

from quanters_gate import workflows


class EmptySnapshotClient:
    def __enter__(self) -> EmptySnapshotClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

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
    monkeypatch.setattr(workflows, "LixingerClient", EmptySnapshotClient)
    args = Namespace(
        max_universe_snapshots=1,
        start="2024-01-01",
        end="2024-01-31",
    )

    with pytest.raises(RuntimeError, match="成分快照为空"):
        workflows.build_universe_history(args)

    assert not (tmp_path / "000300_monthly_snapshots" / "2024-01-31.csv").exists()
