# 定义行情数据源必须提供的结构化接口。

from collections.abc import Callable
from typing import Protocol

import pandas as pd


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
