import json
from pathlib import Path

import pandas as pd

from quanters_gate.storage import atomic_write_csv, atomic_write_json, calculate_sha256


def test_atomic_writers_replace_files_and_remove_temporary_files(tmp_path: Path) -> None:
    csv_path = tmp_path / "nested" / "data.csv"
    json_path = tmp_path / "nested" / "data.json"
    first = pd.DataFrame({"value": [1]})
    second = pd.DataFrame({"value": [2, 3]})

    atomic_write_csv(first, csv_path)
    first_hash = calculate_sha256(csv_path)
    atomic_write_csv(second, csv_path)
    atomic_write_json({"rows": len(second)}, json_path)

    loaded = pd.read_csv(csv_path)
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["value"].tolist() == [2, 3]
    assert metadata == {"rows": 2}
    assert calculate_sha256(csv_path) != first_hash
    assert list(csv_path.parent.glob("*.tmp")) == []
