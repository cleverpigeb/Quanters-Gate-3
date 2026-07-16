import pandas as pd
import pytest

from quanters_gate.research.preprocessing import build_preprocess_summary, preprocess_factors


@pytest.fixture
def factor_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
            "symbol": ["000001", "000002", "000003", "000004"] * 2,
            "test_factor": [1.0, 2.0, 3.0, 100.0, 2.0, 3.0, None, 5.0],
        }
    )


def test_preprocessor_standardizes_each_date_and_preserves_missing_values(
    factor_panel: pd.DataFrame,
) -> None:
    processed = preprocess_factors(factor_panel, ["test_factor"])
    first_day = processed.loc[
        processed["date"] == pd.Timestamp("2024-01-02"),
        "test_factor",
    ]

    assert first_day.mean() == pytest.approx(0.0)
    assert first_day.std(ddof=0) == pytest.approx(1.0)
    assert processed.loc[processed["symbol"] == "000003", "test_factor"].isna().any()


def test_summary_reports_cross_section_coverage(factor_panel: pd.DataFrame) -> None:
    summary = build_preprocess_summary(factor_panel, ["test_factor"])

    assert summary.loc[0, "usable_date_count"] == 2
    assert summary.loc[0, "median_cross_section_size"] == 3.5


def test_preprocessor_rejects_missing_identifier_columns(factor_panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="date"):
        preprocess_factors(factor_panel.drop(columns="date"), ["test_factor"])


def test_preprocessor_rejects_non_positive_mad_scale(factor_panel: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="有限正数"):
        preprocess_factors(factor_panel, ["test_factor"], mad_scale=-1)


def test_preprocessor_rejects_duplicate_security_dates(factor_panel: pd.DataFrame) -> None:
    duplicated = pd.concat([factor_panel, factor_panel.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="重复记录"):
        preprocess_factors(duplicated, ["test_factor"])
