# 提供 DataFrame 输入校验的共用函数。

from collections.abc import Iterable
from math import isfinite

import pandas as pd


def require_columns(data: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    # 确认表格包含指定列，否则给出明确的中文错误。
    missing = set(columns).difference(data.columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"{context}缺少必需列：{names}")


def require_positive(value: int, name: str) -> None:
    # 确认整数参数为正数。
    if value <= 0:
        raise ValueError(f"{name}必须为正数。")


def require_positive_finite(value: float, name: str) -> None:
    # 确认数值有限且为正数。
    try:
        numeric = float(value)
    except TypeError, ValueError:
        raise ValueError(f"{name}必须是有限正数。") from None
    if not isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name}必须是有限正数。")


def require_non_negative_finite(value: float, name: str) -> None:
    # 确认数值有限且不小于零。
    try:
        numeric = float(value)
    except TypeError, ValueError:
        raise ValueError(f"{name}必须是有限非负数。") from None
    if not isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name}必须是有限非负数。")


def require_unique_rows(data: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    # 确认指定业务键不存在重复记录。
    keys = list(columns)
    require_columns(data, keys, context)
    duplicate_count = int(data.duplicated(keys, keep=False).sum())
    if duplicate_count:
        names = ", ".join(keys)
        raise ValueError(f"{context}包含 {duplicate_count} 条重复记录，业务键为：{names}")


def validate_date_range(start_date: object, end_date: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    # 解析并校验闭区间研究日期。
    start = pd.to_datetime(start_date, errors="coerce", utc=True)
    end = pd.to_datetime(end_date, errors="coerce", utc=True)
    if pd.isna(start) or pd.isna(end):
        raise ValueError("研究开始日期和结束日期必须是有效日期。")
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    if start > end:
        raise ValueError("研究开始日期不能晚于结束日期。")
    return start, end
