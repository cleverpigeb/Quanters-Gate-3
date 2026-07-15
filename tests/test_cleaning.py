import pandas as pd

from quanters_gate.data.cleaning import build_cleaning_summary, clean_daily_bars


def _raw_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "symbol": "000001",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
            },
            {
                "date": "2024-01-02",
                "symbol": "000001",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 110,
                "amount": 1210,
            },
            {
                "date": "2024-01-03",
                "symbol": "000001",
                "open": 11,
                "high": 10,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
            },
            {
                "date": "2024-01-04",
                "symbol": "000001",
                "open": 10,
                "high": 10,
                "low": 10,
                "close": 10,
                "volume": 0,
                "amount": 0,
            },
            {
                "date": "invalid",
                "symbol": "000002",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
            },
        ]
    )


def test_cleaner_keeps_latest_duplicate_and_marks_suspension() -> None:
    cleaned = clean_daily_bars(_raw_bars())

    assert len(cleaned) == 2
    assert cleaned.loc[cleaned["date"] == pd.Timestamp("2024-01-02"), "close"].item() == 11
    assert not cleaned.loc[cleaned["date"] == pd.Timestamp("2024-01-04"), "is_tradable"].item()


def test_cleaning_summary_reports_removed_rows() -> None:
    raw = _raw_bars()
    summary = build_cleaning_summary(raw, clean_daily_bars(raw))

    assert summary.loc[0, "removed_rows"] == 3
    assert summary.loc[0, "untradable_rows"] == 1


def test_cleaner_normalizes_timezone_and_preserves_business_columns() -> None:
    raw = _raw_bars().iloc[[0]].copy()
    raw.loc[:, "date"] = "2024-01-02T00:00:00+08:00"
    raw["eligible_on_signal_date"] = True

    cleaned = clean_daily_bars(raw)

    assert cleaned.loc[0, "date"] == pd.Timestamp("2024-01-02")
    assert bool(cleaned.loc[0, "eligible_on_signal_date"])


def test_cleaner_rejects_non_finite_required_values() -> None:
    raw = _raw_bars().iloc[[0]].copy()
    raw["high"] = pd.Series([float("inf")], index=raw.index, dtype="float64")

    assert clean_daily_bars(raw).empty
