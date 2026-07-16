# 管理股票代码、指数成员历史和信号日资格。

from collections.abc import Iterable

import pandas as pd

from quanters_gate.data.dates import normalize_trade_dates
from quanters_gate.validation import require_columns

ELIGIBILITY_COLUMN = "eligible_on_signal_date"


def _normalize_symbol(symbol: object) -> str:
    code = str(symbol).strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"无效的 A 股代码：{symbol}")
    return code


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    # 按输入顺序返回不重复的六位 A 股代码。
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        code = _normalize_symbol(symbol)
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    if not normalized:
        raise ValueError("股票池不能为空。")
    return normalized


def build_index_stock_pool(
    constituents: pd.DataFrame,
    index_code: str,
    as_of_date: str | pd.Timestamp,
) -> pd.DataFrame:
    # 将单次指数成分响应整理为可审计的股票池快照。
    required = ("symbol", "name", "market", "area_code")
    require_columns(constituents, required, "指数成分数据")

    pool = constituents.copy()
    pool["symbol"] = pool["symbol"].map(_normalize_symbol)
    pool["index_code"] = index_code
    pool["as_of_date"] = pd.Timestamp(as_of_date).normalize()
    pool = pool[["as_of_date", "index_code", *required]]
    return pool.drop_duplicates("symbol", keep="last").sort_values("symbol").reset_index(drop=True)


def monthly_rebalance_dates(trading_dates: pd.Series) -> list[pd.Timestamp]:
    # 选择每个自然月最后一个真实交易日。
    dates = normalize_trade_dates(trading_dates).dropna()
    if dates.empty:
        raise ValueError("交易日期序列不能为空。")
    return dates.groupby(dates.dt.to_period("M")).max().tolist()


def build_index_stock_pool_history(
    snapshots: dict[pd.Timestamp, pd.DataFrame],
    index_code: str,
) -> pd.DataFrame:
    # 合并多个点时成分快照。
    if not snapshots:
        raise ValueError("指数成分快照不能为空。")
    empty_dates = [date for date, constituents in snapshots.items() if constituents.empty]
    if empty_dates:
        dates = ", ".join(pd.Timestamp(date).strftime("%Y-%m-%d") for date in empty_dates)
        raise ValueError(f"以下日期的指数成分快照为空：{dates}")
    frames = [
        build_index_stock_pool(constituents, index_code, as_of_date)
        for as_of_date, constituents in snapshots.items()
    ]
    history = pd.concat(frames, ignore_index=True)
    return (
        history.sort_values(["as_of_date", "symbol"])
        .drop_duplicates(["as_of_date", "symbol"], keep="last")
        .reset_index(drop=True)
    )


def attach_membership_eligibility(
    data: pd.DataFrame,
    membership_history: pd.DataFrame,
) -> pd.DataFrame:
    # 保留完整行情，并标记每行在当日是否具备选股资格。
    require_columns(data, ("date", "symbol"), "行情数据")
    require_columns(membership_history, ("as_of_date", "symbol"), "成分历史")

    market = data.drop(columns=[ELIGIBILITY_COLUMN], errors="ignore").copy()
    market["date"] = normalize_trade_dates(market["date"])
    if market["date"].isna().any():
        raise ValueError("行情数据包含无效交易日期。")
    market["symbol"] = market["symbol"].astype("string").str.strip().map(_normalize_symbol)

    history = membership_history[["as_of_date", "symbol"]].copy()
    history["as_of_date"] = normalize_trade_dates(history["as_of_date"])
    history["symbol"] = history["symbol"].astype("string").str.strip()
    history = history.dropna().drop_duplicates(["as_of_date", "symbol"], keep="last")
    if history.empty:
        raise ValueError("成分历史没有可用记录。")
    history["symbol"] = history["symbol"].map(_normalize_symbol)

    schedule = history[["as_of_date"]].drop_duplicates().sort_values("as_of_date")
    dated_market = pd.merge_asof(
        market.sort_values(["date", "symbol"]),
        schedule,
        left_on="date",
        right_on="as_of_date",
        direction="backward",
    )
    eligible_pairs = history.assign(**{ELIGIBILITY_COLUMN: True})
    result = dated_market.merge(
        eligible_pairs,
        on=["as_of_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    result[ELIGIBILITY_COLUMN] = result[ELIGIBILITY_COLUMN].fillna(False).astype(bool)
    return result.drop(columns="as_of_date").sort_values(["symbol", "date"]).reset_index(drop=True)


def select_eligible_signals(data: pd.DataFrame) -> pd.DataFrame:
    # 仅在存在资格列时筛选可选股票，临时股票列表则全部保留。
    if ELIGIBILITY_COLUMN not in data.columns:
        return data.copy()

    normalized = data[ELIGIBILITY_COLUMN].astype("string").str.strip().str.lower()
    mapping = {"true": True, "false": False, "1": True, "0": False}
    invalid = normalized.notna() & ~normalized.isin(mapping)
    if invalid.any():
        values = ", ".join(sorted(normalized.loc[invalid].unique().tolist()))
        raise ValueError(f"信号资格列包含无法识别的布尔值：{values}")
    mask = normalized.map(mapping).fillna(False).astype(bool)
    return data.loc[mask].copy()
