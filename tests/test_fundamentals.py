import pandas as pd

from quanters_gate.data.fundamentals import (
    FINANCIAL_FACTOR_COLUMNS,
    attach_fundamentals_asof,
    cache_fundamental_batch,
    load_cached_fundamentals,
    normalize_financial_abstract,
)


def test_financial_abstract_uses_conservative_statement_update_date() -> None:
    abstract = pd.DataFrame(
        {
            "指标": [
                "净资产收益率_平均",
                "总资产报酬率(ROA)",
                "营业总收入增长率",
                "经营活动净现金/归属母公司的净利润",
            ],
            "20231231": [10.0, 2.0, 5.0, 1.2],
        }
    )
    updates = pd.DataFrame(
        {
            "symbol": ["000001"],
            "report_period": ["2023-12-31"],
            "available_date": ["2024-03-20"],
        }
    )

    result = normalize_financial_abstract(abstract, updates, "000001")

    assert result.columns.tolist() == [
        "symbol",
        "report_period",
        "available_date",
        *FINANCIAL_FACTOR_COLUMNS,
    ]
    assert result.loc[0, "roe_average"] == 10.0
    assert result.loc[0, "operating_cashflow_to_net_income"] == 1.2


def test_fundamentals_are_not_available_on_the_disclosure_day() -> None:
    signals = pd.DataFrame(
        {
            "date": ["2024-03-20", "2024-03-21", "2024-03-22"],
            "symbol": ["000001"] * 3,
        }
    )
    fundamentals = pd.DataFrame(
        {
            "symbol": ["000001"],
            "report_period": ["2023-12-31"],
            "available_date": ["2024-03-20"],
            "roe_average": [10.0],
            "roa": [2.0],
            "revenue_growth_yoy": [5.0],
            "operating_cashflow_to_net_income": [1.2],
        }
    )

    result = attach_fundamentals_asof(signals, fundamentals)

    assert pd.isna(result.loc[0, "roe_average"])
    assert result.loc[1, "roe_average"] == 10.0
    assert result.loc[2, "report_period"] == pd.Timestamp("2023-12-31")


def test_fundamental_cache_is_resumable(tmp_path) -> None:
    class FakeProvider:
        provider_name = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def fetch_financial_abstract(self, _symbol: str) -> pd.DataFrame:
            self.calls += 1
            return pd.DataFrame(
                {
                    "指标": [
                        "净资产收益率_平均",
                        "总资产报酬率(ROA)",
                        "营业总收入增长率",
                        "经营活动净现金/归属母公司的净利润",
                    ],
                    "20231231": [10.0, 2.0, 5.0, 1.2],
                }
            )

        def fetch_financial_statement_updates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "symbol": [symbol],
                    "report_period": ["2023-12-31"],
                    "available_date": ["2024-03-20"],
                }
            )

    provider = FakeProvider()
    assert cache_fundamental_batch(["000001"], provider, tmp_path, max_symbols=1) == (1, 0)
    assert cache_fundamental_batch(["000001"], provider, tmp_path, max_symbols=1) == (0, 0)
    cached = load_cached_fundamentals(["000001"], provider.provider_name, tmp_path)

    assert provider.calls == 1
    assert cached.loc[0, "roe_average"] == 10.0


def test_fundamental_cache_bounds_failed_requests(tmp_path) -> None:
    class FailingProvider:
        provider_name = "fake"

        def fetch_financial_abstract(self, _symbol: str) -> pd.DataFrame:
            raise RuntimeError("模拟接口失败")

        def fetch_financial_statement_updates(self, _symbol: str) -> pd.DataFrame:
            raise AssertionError("不应在摘要失败后请求更新时间")

    assert cache_fundamental_batch(
        ["000001", "000002"],
        FailingProvider(),
        tmp_path,
        max_symbols=1,
    ) == (0, 1)
