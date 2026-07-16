# 提供 DataFrame 输入校验的共用函数。

from collections.abc import Iterable
from math import isfinite
from numbers import Integral, Real

import pandas as pd

BOOLEAN_VALUE_MAPPING = {"true": True, "false": False, "1": True, "0": False}


def require_columns(data: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    # 确认表格包含指定列，否则给出明确的中文错误。
    missing = set(columns).difference(data.columns)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"{context}缺少必需列：{names}")


def require_positive(value: int, name: str) -> None:
    # 确认整数参数为正数。
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f"{name}必须为正整数。")


def require_positive_finite(value: float, name: str) -> None:
    # 确认数值有限且为正数。
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name}必须是有限正数。")
    numeric = float(value)
    if not isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name}必须是有限正数。")


def require_non_negative_finite(value: float, name: str) -> None:
    # 确认数值有限且不小于零。
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name}必须是有限非负数。")
    numeric = float(value)
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


def normalize_boolean_values(values: pd.Series, context: str) -> pd.Series:
    # 将常见布尔表示统一为 bool，并将缺失值保留为 False。
    normalized = values.astype("string").str.strip().str.lower()
    invalid = normalized.notna() & ~normalized.isin(BOOLEAN_VALUE_MAPPING)
    if invalid.any():
        names = "、".join(sorted(normalized.loc[invalid].unique().tolist()))
        raise ValueError(f"{context}包含无法识别的布尔值：{names}")
    return normalized.map(BOOLEAN_VALUE_MAPPING).fillna(False).astype(bool)


def validate_non_overlapping_sample(horizon: int, sample_step: int) -> None:
    # 确保未来收益评估使用互不重叠的抽样窗口。
    require_positive(horizon, "未来收益周期")
    require_positive(sample_step, "抽样步长")
    if sample_step < horizon:
        raise ValueError("抽样步长不能小于未来收益周期，否则评估窗口会重叠。")


def validate_date_range(start_date: object, end_date: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    # 解析并校验闭区间研究日期。
    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except TypeError, ValueError:
        raise ValueError("研究开始日期和结束日期必须是有效日期。") from None
    if pd.isna(start) or pd.isna(end):
        raise ValueError("研究开始日期和结束日期必须是有效日期。")
    if start.tzinfo is not None:
        start = start.tz_convert("Asia/Shanghai").tz_localize(None)
    if end.tzinfo is not None:
        end = end.tz_convert("Asia/Shanghai").tz_localize(None)
    start = start.normalize()
    end = end.normalize()
    if start > end:
        raise ValueError("研究开始日期不能晚于结束日期。")
    return start, end
