from pathlib import Path

import pytest
import requests

from quanters_gate.data.lixinger import LixingerClient


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "code": 1,
            "data": [
                {"date": "2024-01-31T00:00:00+08:00", "close": 100},
                {"date": "2024-01-30T00:00:00+08:00", "close": 99},
            ],
        }


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.request: dict[str, object] = {}

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.request = {"url": url, **kwargs}
        return FakeResponse()

    def close(self) -> None:
        self.closed = True


def test_index_daily_bars_returns_sorted_trading_dates() -> None:
    session = FakeSession()
    with LixingerClient(token="test-token", session=session) as client:
        bars = client.fetch_index_daily_bars("000300", "2024-01-01", "2024-01-31")

    assert len(bars) == 2
    assert bars.loc[0, "date"] < bars.loc[1, "date"]
    assert session.request["headers"] == {"Accept-Encoding": "gzip"}
    assert session.closed


def test_constituent_frame_has_stable_columns_when_response_is_empty() -> None:
    class EmptyResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            return {"code": 1, "data": [{"stockCode": "000300", "constituents": []}]}

    class EmptySession(FakeSession):
        def post(self, url: str, **kwargs: object) -> EmptyResponse:
            return EmptyResponse()

    client = LixingerClient(token="test-token", session=EmptySession())
    constituents = client.fetch_index_constituents("000300", "2024-01-31")

    assert constituents.columns.tolist() == ["symbol", "name", "market", "area_code"]
    assert constituents.empty


def test_blank_explicit_token_falls_back_to_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIXINGER_TOKEN", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("LIXINGER_TOKEN=file-token\n", encoding="utf-8")
    session = FakeSession()

    client = LixingerClient(token="   ", env_path=env_path, session=session)
    client.fetch_index_daily_bars("000300", "2024-01-01", "2024-01-31")

    assert session.request["json"]["token"] == "file-token"


def test_client_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="有限正数"):
        LixingerClient(token="test-token", timeout=0)


def test_network_errors_are_reported_in_chinese() -> None:
    class FailingSession(FakeSession):
        def post(self, url: str, **kwargs: object) -> FakeResponse:
            raise requests.ConnectionError("offline")

    client = LixingerClient(token="test-token", session=FailingSession())

    with pytest.raises(RuntimeError, match="理杏仁接口请求失败"):
        client.fetch_index_daily_bars("000300", "2024-01-01", "2024-01-31")


def test_company_bars_reject_invalid_provider_dates() -> None:
    class InvalidDateResponse(FakeResponse):
        def json(self) -> dict[str, object]:
            return {
                "code": 1,
                "data": [
                    {
                        "date": "invalid",
                        "open": 10,
                        "close": 10,
                        "high": 11,
                        "low": 9,
                        "volume": 100,
                        "amount": 1000,
                    }
                ],
            }

    class InvalidDateSession(FakeSession):
        def post(self, url: str, **kwargs: object) -> InvalidDateResponse:
            return InvalidDateResponse()

    client = LixingerClient(token="test-token", session=InvalidDateSession())

    with pytest.raises(ValueError, match="无效交易日期"):
        client.fetch_daily_bars("000001", "2024-01-01", "2024-01-31", "lxr_fc_rights")
