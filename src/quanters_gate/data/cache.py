# 管理可续跑的逐股票行情缓存。

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quanters_gate.data.dates import normalize_trade_dates
from quanters_gate.data.provider import DailyBarProvider
from quanters_gate.storage import atomic_write_csv, atomic_write_json, calculate_sha256
from quanters_gate.validation import require_columns, require_positive, validate_date_range

CACHE_SCHEMA_VERSION = 2
DATA_SOURCE_COLUMN = "data_source"


def fetch_universe_daily_bars(
    symbols: list[str],
    start_date: str,
    end_date: str,
    provider: DailyBarProvider,
    price_type: str,
) -> pd.DataFrame:
    # 逐只获取行情，并保留其他请求成功的股票。
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for symbol in symbols:
        try:
            frames.append(provider.fetch_daily_bars(symbol, start_date, end_date, price_type))
        except Exception as error:
            failures.append(f"{symbol}：{error}")

    if not frames:
        details = "；".join(failures)
        raise RuntimeError(f"未能获取任何股票行情。{details}")
    if failures:
        print("以下股票获取失败，已跳过：" + "；".join(failures))
    return pd.concat(frames, ignore_index=True)


def _metadata_path(file_path: Path) -> Path:
    return file_path.with_suffix(".meta.json")


def _cache_covers_date_range(
    file_path: Path,
    start_date: str,
    end_date: str,
    price_type: str,
    provider_name: str,
) -> bool:
    metadata_path = _metadata_path(file_path)
    if not file_path.exists() or not metadata_path.exists():
        return False

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return False
        requested_start = pd.Timestamp(start_date).normalize()
        requested_end = pd.Timestamp(end_date).normalize()
        cached_start = pd.Timestamp(metadata["requested_start"]).normalize()
        cached_end = pd.Timestamp(metadata["requested_end"]).normalize()
        observed_start = pd.Timestamp(metadata["observed_start"]).normalize()
        observed_end = pd.Timestamp(metadata["observed_end"]).normalize()
        if metadata.get("schema_version") != CACHE_SCHEMA_VERSION:
            return False
        if metadata.get("provider") != provider_name:
            return False
        if metadata.get("price_type") != price_type:
            return False
        if cached_start > requested_start or cached_end < requested_end:
            return False

        cached = pd.read_csv(
            file_path,
            usecols=lambda column: column in {"date", "symbol", "price_type", DATA_SOURCE_COLUMN},
            dtype={"symbol": "string", "price_type": "string"},
        )
        if cached.empty:
            return False
        if metadata.get("row_count") != len(cached):
            return False
        if metadata.get("content_sha256") != calculate_sha256(file_path):
            return False
        dates = normalize_trade_dates(cached["date"])
        observed_dates_match = dates.min() == observed_start and dates.max() == observed_end
        symbols_match = cached["symbol"].notna().all() and cached["symbol"].eq(file_path.stem).all()
        price_types_match = (
            cached["price_type"].notna().all() and cached["price_type"].eq(price_type).all()
        )
        source_matches = True
        if DATA_SOURCE_COLUMN in cached.columns:
            sources = cached[DATA_SOURCE_COLUMN].astype("string").dropna().unique().tolist()
            source_matches = len(sources) == 1 and metadata.get(DATA_SOURCE_COLUMN) == sources[0]
        elif provider_name == "akshare" or DATA_SOURCE_COLUMN in metadata:
            source_matches = False
        return bool(
            dates.notna().all()
            and observed_dates_match
            and symbols_match
            and price_types_match
            and source_matches
        )
    except KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, pd.errors.ParserError:
        return False


def _write_cache(
    bars: pd.DataFrame,
    file_path: Path,
    start_date: str,
    end_date: str,
    price_type: str,
    provider_name: str,
) -> None:
    require_columns(bars, ("date", "symbol", "price_type"), "行情缓存")
    if bars.empty:
        raise ValueError("不能写入空的行情缓存。")
    start, end = validate_date_range(start_date, end_date)
    symbols = bars["symbol"].astype("string")
    price_types = bars["price_type"].astype("string")
    if symbols.isna().any() or not symbols.eq(file_path.stem).all():
        raise ValueError(f"行情缓存包含不属于股票 {file_path.stem} 的记录。")
    if price_types.isna().any() or not price_types.eq(price_type).all():
        raise ValueError("行情缓存的价格口径与请求不一致。")
    dates = normalize_trade_dates(bars["date"])
    if dates.isna().any():
        raise ValueError("行情缓存包含无效交易日期。")
    data_source: str | None = None
    if DATA_SOURCE_COLUMN in bars.columns:
        sources = bars[DATA_SOURCE_COLUMN].astype("string").dropna().unique().tolist()
        if len(sources) != 1:
            raise ValueError("行情缓存必须包含唯一且非空的数据来源标记。")
        data_source = sources[0]

    metadata_path = _metadata_path(file_path)
    atomic_write_csv(bars, file_path)

    metadata = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "provider": provider_name,
        "requested_start": start.strftime("%Y-%m-%d"),
        "requested_end": end.strftime("%Y-%m-%d"),
        "observed_start": dates.min().strftime("%Y-%m-%d"),
        "observed_end": dates.max().strftime("%Y-%m-%d"),
        "price_type": price_type,
        "row_count": len(bars),
        "content_sha256": calculate_sha256(file_path),
        "built_at": datetime.now(UTC).isoformat(),
    }
    if data_source is not None:
        metadata[DATA_SOURCE_COLUMN] = data_source
    atomic_write_json(metadata, metadata_path)


def cache_daily_bar_batch(
    symbols: list[str],
    start_date: str,
    end_date: str,
    cache_dir: str | Path,
    provider: DailyBarProvider,
    max_symbols: int,
    price_type: str,
) -> dict[str, int]:
    # 缓存有限数量的缺失行情，使批量获取可以安全续跑。
    require_positive(max_symbols, "单批最大股票数")
    validate_date_range(start_date, end_date)
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)

    missing = [
        symbol
        for symbol in symbols
        if not _cache_covers_date_range(
            directory / f"{symbol}.csv",
            start_date,
            end_date,
            price_type,
            provider.provider_name,
        )
    ]
    fetched = 0
    failures: list[str] = []
    for symbol in missing[:max_symbols]:
        try:
            bars = provider.fetch_daily_bars(symbol, start_date, end_date, price_type)
            _write_cache(
                bars,
                directory / f"{symbol}.csv",
                start_date,
                end_date,
                price_type,
                provider.provider_name,
            )
            fetched += 1
        except Exception as error:
            failures.append(f"{symbol}：{error}")

    if failures:
        print("以下股票缓存失败，本批已继续处理其他股票：" + "；".join(failures))

    return {
        "total": len(symbols),
        "cached": len(symbols) - len(missing),
        "fetched": fetched,
        "failed": len(failures),
        "remaining": len(missing) - fetched,
    }


def load_cached_daily_bars(cache_dir: str | Path, symbols: list[str]) -> pd.DataFrame:
    # 将逐股票缓存合并为长表。
    if not symbols:
        raise ValueError("缓存股票列表不能为空。")
    directory = Path(cache_dir)
    missing = [symbol for symbol in symbols if not (directory / f"{symbol}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"仍缺少 {len(missing)} 只股票的行情缓存。")

    frames = [
        pd.read_csv(directory / f"{symbol}.csv", dtype={"symbol": "string"}) for symbol in symbols
    ]
    return pd.concat(frames, ignore_index=True)
