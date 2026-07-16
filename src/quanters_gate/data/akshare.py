# 适配 AKShare 提供的免费 A 股行情与中证指数数据。

import importlib
from typing import Protocol
from unittest.mock import patch

import pandas as pd
import requests

from quanters_gate.data.dates import normalize_trade_dates
from quanters_gate.data.provider import MarketDataProvider
from quanters_gate.validation import require_columns, validate_date_range

_PRICE_TYPE_TO_ADJUST = {
    "lxr_fc_rights": "qfq",
    "ex_rights": "",
}
_BAR_COLUMNS = ["date", "open", "close", "high", "low", "volume", "amount", "turnover"]
DATA_SOURCE_COLUMN = "data_source"
_SINA_REQUEST_TIMEOUT_SECONDS = 30


class AkShareApi(Protocol):
    def stock_zh_a_hist(self, **kwargs: object) -> pd.DataFrame: ...

    def stock_zh_a_daily(self, **kwargs: object) -> pd.DataFrame: ...

    def index_zh_a_hist(self, **kwargs: object) -> pd.DataFrame: ...

    def index_stock_cons_csindex(self, **kwargs: object) -> pd.DataFrame: ...


def _load_akshare() -> AkShareApi:
    try:
        return importlib.import_module("akshare")  # type: ignore[return-value]
    except ImportError:
        raise RuntimeError("未安装 akshare，请先执行 uv sync 安装项目依赖。") from None


def _format_api_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _naive_trade_date(value: pd.Timestamp) -> pd.Timestamp:
    return value.tz_localize(None).normalize()


def _sina_symbol(symbol: str) -> str:
    if symbol.startswith(("4", "8", "92")):
        return f"bj{symbol}"
    if symbol.startswith(("5", "6", "9")):
        return f"sh{symbol}"
    return f"sz{symbol}"


def _normalize_bars(
    data: pd.DataFrame,
    symbol: str,
    price_type: str,
    data_source: str,
) -> pd.DataFrame:
    renamed = data.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover",
        }
    ).copy()
    require_columns(renamed, _BAR_COLUMNS[:-1], f"股票 {symbol} 的 AKShare 日线")
    if "turnover" not in renamed.columns:
        renamed["turnover"] = pd.NA
    renamed["date"] = normalize_trade_dates(renamed["date"])
    if renamed["date"].isna().any():
        raise ValueError(f"股票 {symbol} 的 AKShare 日线包含无效交易日期。")
    renamed["symbol"] = symbol
    renamed["price_type"] = price_type
    renamed[DATA_SOURCE_COLUMN] = data_source
    return (
        renamed[[*_BAR_COLUMNS, "symbol", "price_type", DATA_SOURCE_COLUMN]]
        .sort_values("date")
        .reset_index(drop=True)
    )


class AkShareClient(MarketDataProvider):
    # 将 AKShare 的中文字段和复权选项转换为项目稳定接口。

    provider_name = "akshare"

    def __init__(self, api: AkShareApi | None = None) -> None:
        self._api = api or _load_akshare()

    def close(self) -> None:
        # AKShare 的函数式接口不持有需要关闭的网络会话。
        return None

    def _fetch_eastmoney_daily_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        adjust: str,
    ) -> pd.DataFrame:
        try:
            return self._api.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=_format_api_date(start.strftime("%Y-%m-%d")),
                end_date=_format_api_date(end.strftime("%Y-%m-%d")),
                adjust=adjust,
                timeout=30,
            )
        except Exception as error:
            raise RuntimeError(f"东财接口请求失败：{error}") from None

    def _fetch_sina_daily_bars(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        adjust: str,
    ) -> pd.DataFrame:
        try:
            original_get = requests.get

            def get_with_timeout(*args: object, **kwargs: object) -> requests.Response:
                # AKShare 的新浪适配器没有暴露超时参数，下载流程又是顺序执行，因此仅在调用期间补上超时。
                kwargs.setdefault("timeout", _SINA_REQUEST_TIMEOUT_SECONDS)
                return original_get(*args, **kwargs)

            with patch.object(requests, "get", new=get_with_timeout):
                return self._api.stock_zh_a_daily(
                    symbol=_sina_symbol(symbol),
                    start_date=_format_api_date(start.strftime("%Y-%m-%d")),
                    end_date=_format_api_date(end.strftime("%Y-%m-%d")),
                    adjust=adjust,
                )
        except Exception as error:
            raise RuntimeError(f"新浪接口请求失败：{error}") from None

    def fetch_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        price_type: str,
    ) -> pd.DataFrame:
        # 依次尝试东财和新浪的完整 A 股日线接口。
        start, end = validate_date_range(start_date, end_date)
        start, end = _naive_trade_date(start), _naive_trade_date(end)
        try:
            adjust = _PRICE_TYPE_TO_ADJUST[price_type]
        except KeyError:
            raise ValueError(f"AKShare 不支持项目价格口径：{price_type}") from None
        fetchers = (
            ("eastmoney", self._fetch_eastmoney_daily_bars),
            ("sina", self._fetch_sina_daily_bars),
        )
        failures: list[str] = []
        for data_source, fetcher in fetchers:
            try:
                data = fetcher(symbol, start, end, adjust)
                if data.empty:
                    raise ValueError("接口没有返回数据。")
                result = _normalize_bars(data, symbol, price_type, data_source)
                result = result.loc[result["date"].between(start, end)].copy()
                if result.empty:
                    raise ValueError("接口返回数据不在请求区间内。")
                return result.reset_index(drop=True)
            except (RuntimeError, ValueError) as error:
                failures.append(f"{data_source}：{error}")
        detail = "；".join(failures)
        raise RuntimeError(f"AKShare 获取股票 {symbol} 日线失败：{detail}")

    def fetch_index_daily_bars(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        # 获取指数日线，用于识别每月最后一个真实交易日。
        start, end = validate_date_range(start_date, end_date)
        start, end = _naive_trade_date(start), _naive_trade_date(end)
        try:
            data = self._api.index_zh_a_hist(
                symbol=index_code,
                period="daily",
                start_date=_format_api_date(start.strftime("%Y-%m-%d")),
                end_date=_format_api_date(end.strftime("%Y-%m-%d")),
            )
        except Exception as error:
            raise RuntimeError(f"AKShare 获取指数 {index_code} 日线失败：{error}") from None
        if data.empty:
            raise ValueError(f"指数 {index_code} 没有返回 AKShare 日线数据。")
        result = data.rename(columns={"日期": "date"}).copy()
        require_columns(result, ("date",), f"指数 {index_code} 的 AKShare 日线")
        result["date"] = normalize_trade_dates(result["date"])
        if result["date"].isna().any():
            raise ValueError(f"指数 {index_code} 的 AKShare 日线包含无效交易日期。")
        result = result.loc[result["date"].between(start, end)].sort_values("date")
        if result.empty:
            raise ValueError(f"指数 {index_code} 在请求区间内没有 AKShare 日线数据。")
        return result.reset_index(drop=True)

    def fetch_index_constituents(self, index_code: str, as_of_date: str) -> pd.DataFrame:
        # 仅接受中证网站实际标注日期的快照，避免把当前成员伪装成历史成员。
        requested, _ = validate_date_range(as_of_date, as_of_date)
        requested = _naive_trade_date(requested)
        try:
            data = self._api.index_stock_cons_csindex(symbol=index_code)
        except Exception as error:
            raise RuntimeError(f"AKShare 获取指数 {index_code} 成分股失败：{error}") from None
        if data.empty:
            return pd.DataFrame(columns=["symbol", "name", "market", "area_code"])

        renamed = data.rename(
            columns={
                "日期": "as_of_date",
                "成分券代码": "symbol",
                "成分券名称": "name",
                "交易所": "market",
            }
        ).copy()
        require_columns(
            renamed,
            ("as_of_date", "symbol", "name", "market"),
            f"指数 {index_code} 的 AKShare 成分股",
        )
        snapshot_dates = normalize_trade_dates(renamed["as_of_date"]).dropna().unique()
        if len(snapshot_dates) != 1:
            raise ValueError(f"指数 {index_code} 的 AKShare 成分股包含多个或无效快照日期。")
        snapshot_date = pd.Timestamp(snapshot_dates[0])
        if snapshot_date != requested:
            raise ValueError(
                f"AKShare 仅提供指数 {index_code} 的当前成分快照（{snapshot_date:%Y-%m-%d}），"
                f"不能代替请求的历史日期 {requested:%Y-%m-%d}，否则会引入未来信息。"
            )
        renamed["symbol"] = renamed["symbol"].astype("string").str.strip()
        renamed["area_code"] = "cn"
        return renamed[["symbol", "name", "market", "area_code"]].reset_index(drop=True)
