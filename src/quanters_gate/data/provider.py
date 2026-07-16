# 定义行情数据源必须提供的结构化接口。

from collections.abc import Callable
from typing import Protocol

import pandas as pd

from quanters_gate.data.universe import normalize_symbols
from quanters_gate.validation import require_columns


class DailyBarProvider(Protocol):
    provider_name: str

    def fetch_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        price_type: str,
    ) -> pd.DataFrame: ...


class MarketDataProvider(DailyBarProvider, Protocol):
    def fetch_index_constituents(
        self,
        index_code: str,
        as_of_date: str,
    ) -> pd.DataFrame: ...

    def fetch_index_daily_bars(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame: ...

    def close(self) -> None: ...


type MarketDataProviderFactory = Callable[[], MarketDataProvider]


def fetch_universe_daily_bars(
    symbols: list[str],
    start_date: str,
    end_date: str,
    provider: DailyBarProvider,
    price_type: str,
) -> pd.DataFrame:
    # 顺序获取多只股票行情，并明确报告未成功的股票。
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for symbol in normalize_symbols(symbols):
        try:
            bars = provider.fetch_daily_bars(symbol, start_date, end_date, price_type)
            require_columns(bars, ("symbol", "price_type"), f"股票 {symbol} 的行情响应")
            response_symbols = bars["symbol"].astype("string")
            response_price_types = bars["price_type"].astype("string")
            symbols_match = response_symbols.notna().all() and response_symbols.eq(symbol).all()
            price_types_match = (
                response_price_types.notna().all() and response_price_types.eq(price_type).all()
            )
            if bars.empty or not symbols_match or not price_types_match:
                raise ValueError(f"股票 {symbol} 的行情响应与请求不一致。")
            frames.append(bars)
        except Exception as error:
            failures.append(f"{symbol}：{error}")

    if not frames:
        details = "；".join(failures)
        raise RuntimeError(f"未能获取任何股票行情。{details}")
    if failures:
        print("以下股票获取失败，已跳过：" + "；".join(failures))
    return pd.concat(frames, ignore_index=True)
