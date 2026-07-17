# 清洗财务摘要并按可用日进行 point-in-time 合并。

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import pandas as pd

from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.data.universe import normalize_symbol_values, normalize_symbols
from quanters_gate.storage import atomic_write_csv, atomic_write_json, calculate_sha256
from quanters_gate.validation import require_columns, require_unique_rows

FINANCIAL_FACTOR_COLUMNS = (
    "roe_average",
    "roa",
    "revenue_growth_yoy",
    "operating_cashflow_to_net_income",
)
_METRIC_TO_FACTOR = {
    "净资产收益率_平均": "roe_average",
    "总资产报酬率(ROA)": "roa",
    "营业总收入增长率": "revenue_growth_yoy",
    "经营活动净现金/归属母公司的净利润": "operating_cashflow_to_net_income",
}
_REPORT_PERIOD_PATTERN = re.compile(r"^\d{8}$")


class FundamentalDataProvider(Protocol):
    provider_name: str

    def fetch_financial_abstract(self, symbol: str) -> pd.DataFrame: ...

    def fetch_financial_statement_updates(self, symbol: str) -> pd.DataFrame: ...


def _cache_paths(directory: Path, symbol: str) -> tuple[Path, Path]:
    return directory / f"{symbol}.csv", directory / f"{symbol}.meta.json"


def _read_cached_fundamentals(
    directory: Path, symbol: str, provider_name: str
) -> pd.DataFrame | None:
    csv_path, metadata_path = _cache_paths(directory, symbol)
    if not csv_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        cached = pd.read_csv(csv_path, dtype={"symbol": "string"})
    except OSError, ValueError, json.JSONDecodeError:
        return None
    if (
        metadata.get("provider") != provider_name
        or metadata.get("symbol") != symbol
        or metadata.get("content_sha256") != calculate_sha256(csv_path)
    ):
        return None
    try:
        require_columns(
            cached,
            ("symbol", "report_period", "available_date", *FINANCIAL_FACTOR_COLUMNS),
            f"股票 {symbol} 的财务缓存",
        )
        cached["symbol"] = normalize_symbol_values(cached["symbol"], f"股票 {symbol} 的财务缓存")
        if not cached["symbol"].eq(symbol).all():
            return None
        cached["report_period"] = pd.to_datetime(cached["report_period"], errors="coerce")
        cached["available_date"] = pd.to_datetime(cached["available_date"], errors="coerce")
        if cached[["report_period", "available_date"]].isna().any().any():
            return None
        require_unique_rows(cached, ("symbol", "report_period"), f"股票 {symbol} 的财务缓存")
    except TypeError, ValueError:
        return None
    return cached


def cache_fundamental_batch(
    symbols: Sequence[str],
    provider: FundamentalDataProvider,
    directory: Path,
    max_symbols: int,
) -> tuple[int, int]:
    # 顺序补齐缺失财务缓存；失败记录不会覆盖已有的有效缓存。
    if max_symbols <= 0:
        raise ValueError("单批最大财务股票数必须为正整数。")
    attempted = 0
    completed = 0
    failures = 0
    for symbol in normalize_symbols(symbols):
        if _read_cached_fundamentals(directory, symbol, provider.provider_name) is not None:
            continue
        if attempted >= max_symbols:
            break
        attempted += 1
        try:
            normalized = normalize_financial_abstract(
                provider.fetch_financial_abstract(symbol),
                provider.fetch_financial_statement_updates(symbol),
                symbol,
            )
            if normalized.empty:
                raise ValueError("财务摘要在可用日合并后为空。")
            csv_path, metadata_path = _cache_paths(directory, symbol)
            atomic_write_csv(normalized, csv_path)
            atomic_write_json(
                {
                    "schema_version": 1,
                    "provider": provider.provider_name,
                    "symbol": symbol,
                    "row_count": len(normalized),
                    "content_sha256": calculate_sha256(csv_path),
                },
                metadata_path,
            )
            completed += 1
        except (RuntimeError, ValueError, OSError) as error:
            failures += 1
            print(f"股票 {symbol} 的财务数据获取失败：{error}")
    return completed, failures


def load_cached_fundamentals(
    symbols: Sequence[str],
    provider_name: str,
    directory: Path,
) -> pd.DataFrame:
    # 仅合并通过完整性校验的逐股票缓存。
    frames = [
        cached
        for symbol in normalize_symbols(symbols)
        if (cached := _read_cached_fundamentals(directory, symbol, provider_name)) is not None
    ]
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "report_period", "available_date", *FINANCIAL_FACTOR_COLUMNS]
        )
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["symbol", "report_period"])
        .reset_index(drop=True)
    )


def normalize_financial_abstract(
    abstract: pd.DataFrame,
    updates: pd.DataFrame,
    symbol: str,
) -> pd.DataFrame:
    # 将 AKShare 指标宽表转换为按报告期排列的稳定因子字段。
    require_columns(abstract, ("指标",), f"股票 {symbol} 的财务摘要")
    require_columns(
        updates, ("symbol", "report_period", "available_date"), f"股票 {symbol} 的更新时间"
    )
    period_columns = [
        column for column in abstract.columns if _REPORT_PERIOD_PATTERN.fullmatch(str(column))
    ]
    if not period_columns:
        raise ValueError(f"股票 {symbol} 的财务摘要不包含报告期列。")
    selected = abstract.loc[abstract["指标"].isin(_METRIC_TO_FACTOR), ["指标", *period_columns]]
    long = selected.melt(
        id_vars="指标",
        value_vars=period_columns,
        var_name="report_period",
        value_name="value",
    )
    long["report_period"] = pd.to_datetime(long["report_period"], format="%Y%m%d", errors="coerce")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long["factor"] = long["指标"].map(_METRIC_TO_FACTOR)
    values = (
        long.dropna(subset=["report_period", "factor"])
        .pivot(index="report_period", columns="factor", values="value")
        .reindex(columns=FINANCIAL_FACTOR_COLUMNS)
        .reset_index()
    )
    normalized_updates = updates.copy()
    normalized_updates["symbol"] = normalize_symbol_values(
        normalized_updates["symbol"],
        f"股票 {symbol} 的更新时间",
    )
    normalized_updates["report_period"] = pd.to_datetime(
        normalized_updates["report_period"],
        errors="coerce",
    ).dt.normalize()
    normalized_updates["available_date"] = pd.to_datetime(
        normalized_updates["available_date"],
        errors="coerce",
    ).dt.normalize()
    normalized_updates = normalized_updates.dropna(subset=["report_period", "available_date"])
    require_unique_rows(
        normalized_updates, ("symbol", "report_period"), f"股票 {symbol} 的更新时间"
    )
    result = values.merge(
        normalized_updates[["symbol", "report_period", "available_date"]],
        on="report_period",
        how="inner",
        validate="one_to_one",
    )
    return (
        result[["symbol", "report_period", "available_date", *FINANCIAL_FACTOR_COLUMNS]]
        .sort_values("report_period")
        .reset_index(drop=True)
    )


def attach_fundamentals_asof(
    signals: pd.DataFrame,
    fundamentals: pd.DataFrame,
    factor_columns: Sequence[str] = FINANCIAL_FACTOR_COLUMNS,
) -> pd.DataFrame:
    # 每个信号日仅使用此前已披露的最新一份财务数据，披露当日不允许使用。
    factors = list(factor_columns)
    require_columns(signals, ("date", "symbol"), "财务因子合并输入")
    require_columns(
        fundamentals,
        ("symbol", "report_period", "available_date", *factors),
        "财务因子面板",
    )
    result = signals.copy()
    result["date"] = normalize_required_trade_dates(result["date"], "财务因子合并输入")
    result["symbol"] = normalize_symbol_values(result["symbol"], "财务因子合并输入")
    require_unique_rows(result, ("date", "symbol"), "财务因子合并输入")

    prepared = fundamentals.copy()
    prepared["symbol"] = normalize_symbol_values(prepared["symbol"], "财务因子面板")
    prepared["available_date"] = pd.to_datetime(
        prepared["available_date"], errors="coerce"
    ).dt.normalize()
    prepared["report_period"] = pd.to_datetime(
        prepared["report_period"], errors="coerce"
    ).dt.normalize()
    prepared = prepared.dropna(subset=["available_date", "report_period"])
    require_unique_rows(prepared, ("symbol", "report_period"), "财务因子面板")

    frames: list[pd.DataFrame] = []
    for symbol, signal_group in result.groupby("symbol", sort=True, observed=True):
        financial_group = prepared.loc[prepared["symbol"] == symbol]
        if financial_group.empty:
            frames.append(signal_group.assign(**{factor: pd.NA for factor in factors}))
            continue
        merged = pd.merge_asof(
            signal_group.sort_values("date"),
            financial_group.sort_values("available_date")[
                ["available_date", "report_period", *factors]
            ],
            left_on="date",
            right_on="available_date",
            direction="backward",
            allow_exact_matches=False,
        )
        frames.append(merged.drop(columns="available_date"))
    return (
        pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)
    )
