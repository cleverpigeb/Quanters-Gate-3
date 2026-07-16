# 提供跨模块共用的交易日期处理。

import pandas as pd


def normalize_trade_dates(values: pd.Series) -> pd.Series:
    # 将外部时间戳统一为无时区的上海交易日期。
    timestamps = pd.to_datetime(values, errors="coerce", utc=True)
    return timestamps.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()


def normalize_required_trade_dates(values: pd.Series, context: str) -> pd.Series:
    # 标准化交易日期，并拒绝任何无法解析的记录。
    dates = normalize_trade_dates(values)
    if dates.isna().any():
        raise ValueError(f"{context}包含无效交易日期。")
    return dates


def normalize_trade_dates_with_positions(
    values: pd.Series,
    context: str,
) -> tuple[pd.Series, pd.Series]:
    # 标准化全市场交易日期，并映射连续位置以识别个股历史缺口。
    dates = normalize_required_trade_dates(values, context)
    unique_dates = pd.Index(dates.unique()).sort_values()
    position_by_date = pd.Series(range(len(unique_dates)), index=unique_dates)
    positions = dates.map(position_by_date).astype("int64")
    return dates, positions
