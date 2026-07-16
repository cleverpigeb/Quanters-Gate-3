import pandas as pd
import pytest
import requests

from quanters_gate.data.akshare import AkShareClient


class FakeAkShare:
    def __init__(self) -> None:
        self.stock_request: dict[str, object] = {}
        self.stock_requests: list[dict[str, object]] = []
        self.sina_request: dict[str, object] = {}
        self.index_request: dict[str, object] = {}

    def stock_zh_a_hist(self, **kwargs: object) -> pd.DataFrame:
        self.stock_request = kwargs
        self.stock_requests.append(kwargs)
        return pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-03"],
                "开盘": [10.0, 11.0],
                "收盘": [11.0, 12.0],
                "最高": [12.0, 13.0],
                "最低": [9.0, 10.0],
                "成交量": [100, 110],
                "成交额": [1000, 1200],
                "换手率": [1.2, 1.3],
            }
        )

    def index_zh_a_hist(self, **kwargs: object) -> pd.DataFrame:
        self.index_request = kwargs
        return pd.DataFrame({"日期": ["2024-01-31", "2024-02-29"]})

    def stock_zh_a_daily(self, **kwargs: object) -> pd.DataFrame:
        self.sina_request = kwargs
        return pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-03"],
                "open": [10.0, 11.0],
                "close": [11.0, 12.0],
                "high": [12.0, 13.0],
                "low": [9.0, 10.0],
                "volume": [100, 110],
                "amount": [1000, 1200],
                "turnover": [1.2, 1.3],
            }
        )

    def index_stock_cons_csindex(self, **_kwargs: object) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "日期": ["2024-01-31", "2024-01-31"],
                "成分券代码": ["000001", "600000"],
                "成分券名称": ["平安银行", "浦发银行"],
                "交易所": ["深圳证券交易所", "上海证券交易所"],
            }
        )


def test_stock_bars_map_price_conventions_and_chinese_columns() -> None:
    api = FakeAkShare()
    client = AkShareClient(api)

    research = client.fetch_daily_bars("000001", "2024-01-01", "2024-01-31", "lxr_fc_rights")
    execution = client.fetch_daily_bars("000001", "2024-01-01", "2024-01-31", "ex_rights")

    assert api.stock_request["start_date"] == "20240101"
    assert api.stock_request["end_date"] == "20240131"
    assert api.stock_request["timeout"] == 30
    assert [request["adjust"] for request in api.stock_requests] == ["qfq", ""]
    assert research.columns.tolist() == [
        "date",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "amount",
        "turnover",
        "symbol",
        "price_type",
        "data_source",
    ]
    assert research["price_type"].eq("lxr_fc_rights").all()
    assert execution["price_type"].eq("ex_rights").all()
    assert research["data_source"].eq("eastmoney").all()


def test_stock_bars_fall_back_to_sina_after_eastmoney_fails() -> None:
    class EastmoneyFailure(FakeAkShare):
        def stock_zh_a_hist(self, **_kwargs: object) -> pd.DataFrame:
            raise ConnectionError("模拟东财断开连接")

    api = EastmoneyFailure()
    result = AkShareClient(api).fetch_daily_bars(
        "000001",
        "2024-01-01",
        "2024-01-31",
        "lxr_fc_rights",
    )

    assert api.sina_request == {
        "symbol": "sz000001",
        "start_date": "20240101",
        "end_date": "20240131",
        "adjust": "qfq",
    }
    assert result["data_source"].eq("sina").all()


def test_stock_bars_use_beijing_sina_prefix_for_920_codes() -> None:
    class EastmoneyFailure(FakeAkShare):
        def stock_zh_a_hist(self, **_kwargs: object) -> pd.DataFrame:
            raise ConnectionError("模拟东财断开连接")

    api = EastmoneyFailure()
    AkShareClient(api).fetch_daily_bars("920001", "2024-01-01", "2024-01-31", "lxr_fc_rights")

    assert api.sina_request["symbol"] == "bj920001"


def test_sina_fallback_adds_a_request_timeout(monkeypatch) -> None:
    class EastmoneyFailure(FakeAkShare):
        def stock_zh_a_hist(self, **_kwargs: object) -> pd.DataFrame:
            raise ConnectionError("模拟东财断开连接")

        def stock_zh_a_daily(self, **kwargs: object) -> pd.DataFrame:
            requests.get("https://example.invalid")
            return super().stock_zh_a_daily(**kwargs)

    request_kwargs: dict[str, object] = {}

    def fake_get(*_args: object, **kwargs: object) -> object:
        request_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(requests, "get", fake_get)
    AkShareClient(EastmoneyFailure()).fetch_daily_bars(
        "000001",
        "2024-01-01",
        "2024-01-31",
        "lxr_fc_rights",
    )

    assert request_kwargs["timeout"] == 30


def test_index_bars_use_akshare_dates() -> None:
    api = FakeAkShare()
    bars = AkShareClient(api).fetch_index_daily_bars("000300", "2024-01-01", "2024-02-29")

    assert api.index_request["symbol"] == "000300"
    assert bars["date"].tolist() == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")]


def test_constituents_reject_a_current_snapshot_for_a_historical_request() -> None:
    with pytest.raises(ValueError, match="未来信息"):
        AkShareClient(FakeAkShare()).fetch_index_constituents("000300", "2023-12-29")


def test_constituents_accept_the_source_snapshot_date() -> None:
    constituents = AkShareClient(FakeAkShare()).fetch_index_constituents("000300", "2024-01-31")

    assert constituents.to_dict("records") == [
        {"symbol": "000001", "name": "平安银行", "market": "深圳证券交易所", "area_code": "cn"},
        {"symbol": "600000", "name": "浦发银行", "market": "上海证券交易所", "area_code": "cn"},
    ]
