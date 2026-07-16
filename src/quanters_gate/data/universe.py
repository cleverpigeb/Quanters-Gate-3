# 管理股票代码、指数成员历史和信号日资格。

from collections.abc import Iterable

import pandas as pd

from quanters_gate.data.dates import normalize_required_trade_dates
from quanters_gate.validation import (
    normalize_boolean_values,
    require_columns,
    require_unique_rows,
)

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


def normalize_symbol_values(values: pd.Series, context: str) -> pd.Series:
    # 标准化表格中的 A 股代码，并拒绝缺失或非六位数字记录。
    symbols = values.astype("string").str.strip()
    invalid = symbols.isna() | ~symbols.str.fullmatch(r"\d{6}", na=False)
    if invalid.any():
        raise ValueError(f"{context}包含无效 A 股代码。")
    return symbols


def build_index_stock_pool(
    constituents: pd.DataFrame,
    index_code: str,
    as_of_date: str | pd.Timestamp,
) -> pd.DataFrame:
    # 将单次指数成分响应整理为可审计的股票池快照。
    required = ("symbol", "name", "market", "area_code")
    require_columns(constituents, required, "指数成分数据")

    pool = constituents.copy()
    if pool.empty:
        raise ValueError("指数成分数据不能为空。")
    if pool[list(required)].isna().any().any():
        raise ValueError("指数成分数据包含缺失的股票代码、名称或市场信息。")
    text_columns = ["symbol", "name", "market", "area_code"]
    if (
        pool[text_columns]
        .astype("string")
        .apply(lambda column: column.str.strip().eq(""))
        .any()
        .any()
    ):
        raise ValueError("指数成分数据包含空白的股票代码、名称或市场信息。")
    pool["symbol"] = pool["symbol"].map(_normalize_symbol)
    pool["index_code"] = _normalize_symbol(index_code)
    pool["as_of_date"] = normalize_required_trade_dates(
        pd.Series([as_of_date]),
        "指数成分快照",
    ).iloc[0]
    pool = pool[["as_of_date", "index_code", *required]]
    return pool.drop_duplicates("symbol", keep="last").sort_values("symbol").reset_index(drop=True)


def monthly_rebalance_dates(trading_dates: pd.Series) -> list[pd.Timestamp]:
    # 选择每个自然月最后一个真实交易日。
    dates = normalize_required_trade_dates(trading_dates, "交易日期序列")
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


def normalize_membership_history(membership_history: pd.DataFrame) -> pd.DataFrame:
    # 标准化并严格校验可审计的历史成分记录。
    require_columns(membership_history, ("as_of_date", "symbol"), "成分历史")
    history = membership_history.copy()
    history["as_of_date"] = normalize_required_trade_dates(history["as_of_date"], "成分历史")
    history["symbol"] = normalize_symbol_values(history["symbol"], "成分历史")
    if history.empty:
        raise ValueError("成分历史没有可用记录。")
    require_unique_rows(history, ("as_of_date", "symbol"), "成分历史")
    return history.sort_values(["as_of_date", "symbol"]).reset_index(drop=True)


def attach_membership_eligibility(
    data: pd.DataFrame,
    membership_history: pd.DataFrame,
) -> pd.DataFrame:
    # 保留完整行情，并标记每行在当日是否具备选股资格。
    require_columns(data, ("date", "symbol"), "行情数据")

    market = data.drop(columns=[ELIGIBILITY_COLUMN], errors="ignore").copy()
    market["date"] = normalize_required_trade_dates(market["date"], "行情数据")
    market["symbol"] = normalize_symbol_values(market["symbol"], "行情数据")
    require_unique_rows(market, ("date", "symbol"), "行情数据")

    history = normalize_membership_history(membership_history)[["as_of_date", "symbol"]]

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

    mask = normalize_boolean_values(data[ELIGIBILITY_COLUMN], "信号资格列")
    return data.loc[mask].copy()
