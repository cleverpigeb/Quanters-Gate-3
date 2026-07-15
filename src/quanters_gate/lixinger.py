"""封装研究流水线使用的理杏仁接口。"""

import os
from pathlib import Path
from types import TracebackType

import pandas as pd
import requests

from quanters_gate.paths import PROJECT_ROOT
from quanters_gate.settings import (
    LIXINGER_COMPANY_CANDLESTICK_URL,
    LIXINGER_INDEX_CANDLESTICK_URL,
    LIXINGER_INDEX_CONSTITUENTS_URL,
    LIXINGER_RESEARCH_PRICE_TYPE,
)
from quanters_gate.validation import require_positive_finite, validate_date_range


class LixingerClient:
    """管理本项目所需的理杏仁请求、鉴权和响应校验。"""

    def __init__(
        self,
        token: str | None = None,
        env_path: str | Path | None = None,
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        require_positive_finite(timeout, "接口超时时间")
        path = Path(env_path) if env_path else PROJECT_ROOT / ".env"
        provided_token = token.strip() if token else ""
        self._token = provided_token or self._load_token(path)
        self._session = session or requests.Session()
        self._timeout = timeout

    def __enter__(self) -> LixingerClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """释放底层 HTTP 会话。"""
        close = getattr(self._session, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _load_token(env_path: Path) -> str:
        token = os.environ.get("LIXINGER_TOKEN")
        if token and token.strip():
            return token.strip()

        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == "LIXINGER_TOKEN":
                    token = value.strip().strip('"').strip("'")
                    if token:
                        return token
        raise RuntimeError("缺少 LIXINGER_TOKEN，请将其写入项目根目录的本地 .env 文件。")

    def _post(self, url: str, payload: dict[str, object]) -> list[dict[str, object]]:
        try:
            response = self._session.post(
                url,
                json={"token": self._token, **payload},
                headers={"Accept-Encoding": "gzip"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException:
            raise RuntimeError("理杏仁接口请求失败，请检查网络连接、Token 和接口状态。") from None
        except ValueError:
            raise RuntimeError("理杏仁接口返回的内容不是有效 JSON。") from None
        if not isinstance(result, dict):
            raise RuntimeError("理杏仁接口返回了无法识别的响应结构。")
        if result.get("code") != 1:
            message = result.get("message", "未知错误")
            raise RuntimeError(f"理杏仁接口返回错误：{message}")

        data = result.get("data")
        if not isinstance(data, list):
            raise RuntimeError("理杏仁接口返回了无法识别的数据结构。")
        return data

    def fetch_index_constituents(self, index_code: str, as_of_date: str) -> pd.DataFrame:
        """获取指定日期的指数成分股快照。"""
        date, _ = validate_date_range(as_of_date, as_of_date)
        records = self._post(
            LIXINGER_INDEX_CONSTITUENTS_URL,
            {
                "stockCodes": [index_code],
                "date": date.strftime("%Y-%m-%d"),
            },
        )
        if len(records) != 1 or records[0].get("stockCode") != index_code:
            raise RuntimeError(f"指数 {index_code} 的成分股响应与请求不一致。")

        constituents = records[0].get("constituents", [])
        if not isinstance(constituents, list):
            raise RuntimeError(f"指数 {index_code} 的成分股列表结构无效。")

        rows: list[dict[str, object]] = []
        for constituent in constituents:
            if not isinstance(constituent, dict):
                raise RuntimeError(f"指数 {index_code} 包含无法识别的成分股记录。")
            name = constituent.get("stockName", {})
            rows.append(
                {
                    "symbol": constituent.get("stockCode"),
                    "name": name.get("cmn_hans_cn") if isinstance(name, dict) else None,
                    "market": constituent.get("market"),
                    "area_code": constituent.get("areaCode"),
                }
            )
        return pd.DataFrame(rows, columns=["symbol", "name", "market", "area_code"])

    def fetch_index_daily_bars(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """获取指数日线，用于构造真实交易日历。"""
        start, end = validate_date_range(start_date, end_date)
        records = self._post(
            LIXINGER_INDEX_CANDLESTICK_URL,
            {
                "stockCode": index_code,
                "type": "normal",
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
            },
        )
        data = pd.DataFrame(records)
        if data.empty or "date" not in data.columns:
            raise RuntimeError(f"指数 {index_code} 没有返回交易日期。")
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        if data["date"].isna().any():
            raise ValueError(f"指数 {index_code} 返回了无效交易日期。")
        return data.sort_values("date").reset_index(drop=True)

    def fetch_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        price_type: str = LIXINGER_RESEARCH_PRICE_TYPE,
    ) -> pd.DataFrame:
        """按明确的价格口径获取个股日线。"""
        start, end = validate_date_range(start_date, end_date)
        records = self._post(
            LIXINGER_COMPANY_CANDLESTICK_URL,
            {
                "stockCode": symbol,
                "type": price_type,
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
            },
        )
        if not records:
            raise ValueError(f"股票 {symbol} 没有返回日线数据。")

        data = pd.DataFrame(records).rename(columns={"to_r": "turnover"})
        required = ["date", "open", "close", "high", "low", "volume", "amount"]
        missing = set(required).difference(data.columns)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"股票 {symbol} 的日线缺少字段：{names}")

        data["symbol"] = symbol
        data["price_type"] = price_type
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        if data["date"].isna().any():
            raise ValueError(f"股票 {symbol} 返回了无效交易日期。")
        for column in [*required[1:], "turnover"]:
            if column in data.columns:
                data[column] = pd.to_numeric(data[column], errors="coerce")

        output_columns = [*required, "symbol", "turnover", "price_type"]
        return (
            data[[column for column in output_columns if column in data.columns]]
            .sort_values("date")
            .reset_index(drop=True)
        )
