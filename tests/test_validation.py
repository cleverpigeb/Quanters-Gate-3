import pandas as pd
import pytest

from quanters_gate.validation import (
    require_non_negative_finite,
    require_positive,
    require_positive_finite,
    validate_date_range,
)


def test_date_range_preserves_the_shanghai_calendar_date() -> None:
    start, end = validate_date_range(
        "2024-01-01T00:00:00+08:00",
        "2024-01-31T23:00:00+08:00",
    )

    assert start == pd.Timestamp("2024-01-01")
    assert end == pd.Timestamp("2024-01-31")


@pytest.mark.parametrize("value", [True, 1.5])
def test_positive_integer_validation_rejects_non_integers(value: object) -> None:
    with pytest.raises(ValueError, match="正整数"):
        require_positive(value, "测试参数")


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (require_positive_finite, "1.0"),
        (require_positive_finite, True),
        (require_non_negative_finite, "0.0"),
        (require_non_negative_finite, False),
    ],
)
def test_finite_number_validation_rejects_non_numeric_types(validator, value: object) -> None:
    with pytest.raises(ValueError, match="有限"):
        validator(value, "测试参数")
