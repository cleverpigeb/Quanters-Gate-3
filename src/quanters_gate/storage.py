# 提供可复用的原子文件写入与内容校验。

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pandas as pd

HASH_CHUNK_SIZE = 1024 * 1024


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.tmp")


def atomic_write_csv(
    data: pd.DataFrame,
    path: str | Path,
    encoding: str = "utf-8-sig",
) -> None:
    # 先写入同目录临时文件，再原子替换目标 CSV。
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(target)
    try:
        data.to_csv(temporary, index=False, encoding=encoding)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(data: Mapping[str, object], path: str | Path) -> None:
    # 先写入同目录临时文件，再原子替换目标 JSON。
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(target)
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def calculate_sha256(path: str | Path) -> str:
    # 分块计算文件的 SHA-256 内容摘要。
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
