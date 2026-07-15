"""提供跨模块共用的交易日期处理。"""

import pandas as pd


def normalize_trade_dates(values: pd.Series) -> pd.Series:
    """将外部时间戳统一为无时区的上海交易日期。"""
    timestamps = pd.to_datetime(values, errors="coerce", utc=True)
    return timestamps.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
