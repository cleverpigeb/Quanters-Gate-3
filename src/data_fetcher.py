import os
from pathlib import Path

import pandas as pd
import requests

from config.paths import PROJECT_ROOT
from config.settings import (
    LIXINGER_COMPANY_CANDLESTICK_URL,
    LIXINGER_INDEX_CANDLESTICK_URL,
    LIXINGER_INDEX_CONSTITUENTS_URL,
    LIXINGER_RESEARCH_PRICE_TYPE,
)


class LixingerClient:
    """Small client for the Lixinger endpoints used by this research pipeline."""

    def __init__(
        self,
        token: str | None = None,
        env_path: str | Path | None = None,
        session: requests.Session | None = None,
        timeout: int = 30,
    ) -> None:
        self._token = token or self._load_token(Path(env_path) if env_path else PROJECT_ROOT / ".env")
        self._session = session or requests.Session()
        self._timeout = timeout

    @staticmethod
    def _load_token(env_path: Path) -> str:
        token = os.environ.get("LIXINGER_TOKEN")
        if token:
            return token.strip()
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("LIXINGER_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        raise RuntimeError("LIXINGER_TOKEN is missing. Add it to the local .env file.")

    def _post(self, url: str, payload: dict[str, object]) -> list[dict[str, object]]:
        response = self._session.post(
            url,
            json={"token": self._token, **payload},
            headers={"Accept-Encoding": "gzip"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 1:
            raise RuntimeError(f"Lixinger API error: {result.get('message', 'unknown error')}")
        data = result.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Lixinger API returned an unexpected data payload.")
        return data

    def fetch_index_constituents(self, index_code: str, as_of_date: str) -> pd.DataFrame:
        """Fetch one point-in-time index constituent snapshot from Lixinger."""
        records = self._post(
            LIXINGER_INDEX_CONSTITUENTS_URL,
            {"stockCodes": [index_code], "date": pd.Timestamp(as_of_date).strftime("%Y-%m-%d")},
        )
        if len(records) != 1 or records[0].get("stockCode") != index_code:
            raise RuntimeError(f"Unexpected constituent response for index {index_code}.")

        rows = []
        for constituent in records[0].get("constituents", []):
            name = constituent.get("stockName", {})
            rows.append(
                {
                    "symbol": constituent.get("stockCode"),
                    "name": name.get("cmn_hans_cn") if isinstance(name, dict) else None,
                    "market": constituent.get("market"),
                    "area_code": constituent.get("areaCode"),
                }
            )
        return pd.DataFrame(rows)

    def fetch_index_daily_bars(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch index daily bars to derive a real exchange trading calendar."""
        records = self._post(
            LIXINGER_INDEX_CANDLESTICK_URL,
            {
                "stockCode": index_code,
                "type": "normal",
                "startDate": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
                "endDate": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
            },
        )
        data = pd.DataFrame(records)
        if data.empty or "date" not in data.columns:
            raise RuntimeError(f"No index trading dates returned for {index_code}.")
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        return data.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    def fetch_index_constituent_history(
        self,
        index_code: str,
        as_of_dates: list[pd.Timestamp],
    ) -> dict[pd.Timestamp, pd.DataFrame]:
        """Fetch constituent snapshots for a supplied set of rebalancing dates."""
        return {
            date: self.fetch_index_constituents(index_code, date.strftime("%Y-%m-%d"))
            for date in as_of_dates
        }

    def fetch_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        price_type: str = LIXINGER_RESEARCH_PRICE_TYPE,
    ) -> pd.DataFrame:
        """Fetch daily company candles using an explicit Lixinger price convention."""
        records = self._post(
            LIXINGER_COMPANY_CANDLESTICK_URL,
            {
                "stockCode": symbol,
                "type": price_type,
                "startDate": pd.Timestamp(start_date).strftime("%Y-%m-%d"),
                "endDate": pd.Timestamp(end_date).strftime("%Y-%m-%d"),
            },
        )
        if not records:
            raise ValueError(f"No daily bars returned for {symbol}.")

        data = pd.DataFrame(records).rename(columns={"to_r": "turnover"})
        required_columns = ["date", "open", "close", "high", "low", "volume", "amount"]
        missing = set(required_columns).difference(data.columns)
        if missing:
            raise ValueError(f"Unexpected daily-bar columns for {symbol}: {missing}")
        data["symbol"] = symbol
        data["price_type"] = price_type
        data["date"] = pd.to_datetime(data["date"])
        for column in required_columns[1:] + ["turnover"]:
            if column in data.columns:
                data[column] = pd.to_numeric(data[column], errors="coerce")
        keep_columns = required_columns + ["symbol", "turnover", "price_type"]
        return data[[column for column in keep_columns if column in data.columns]]


def fetch_universe_daily_bars(
    symbols: list[str],
    start_date: str,
    end_date: str,
    client: LixingerClient | None = None,
    price_type: str = LIXINGER_RESEARCH_PRICE_TYPE,
) -> pd.DataFrame:
    """Fetch one price panel while preserving usable symbols if individual requests fail."""
    lixinger = client or LixingerClient()
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for symbol in symbols:
        try:
            frames.append(lixinger.fetch_daily_bars(symbol, start_date, end_date, price_type))
        except Exception as error:
            failures.append(f"{symbol}: {error}")
    if not frames:
        raise RuntimeError("No stock data could be fetched. " + "; ".join(failures))
    if failures:
        print("Skipped symbols: " + "; ".join(failures))
    return pd.concat(frames, ignore_index=True)
