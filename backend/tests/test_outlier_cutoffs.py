"""Outliers: which columns are checked, and cut-offs by usual range, percentile or own values."""

import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.detectors.outliers import detect_outliers
from app.models import FixOutliers
from app.transform import apply_steps
from app.values import is_identifier

rng = np.random.default_rng(11)


def column(values, name: str) -> pd.Series:
    return pd.Series([str(v) for v in values], dtype="str", name=name)


def frame(*columns: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({c.name: c for c in columns})


# Ages with two typos, and enough values for percentiles.
AGES = column(list(rng.integers(20, 70, 198)) + [250, 199], "age")


# ------------------------------------------------------------------- which columns are checked


@pytest.mark.parametrize(
    "series",
    [
        pytest.param(column([1, 1, 2, 2, 3, 900] * 5, "store_id"), id="repeating foreign key"),
        pytest.param(column([1, 2, 3, 99999] * 5, "FKbusinessAddress"), id="FK prefix"),
        pytest.param(column(["02134", "10001", "60601", "94105"] * 5, "zip"), id="zip codes"),
        pytest.param(column(["0244123456", "0201234567"] * 5, "contact"), id="leading zeros"),
        pytest.param(column([233244000000 + i for i in range(30)], "customer_phone"), id="phone"),
        pytest.param(column(range(1000, 1040), "row"), id="unique sequential numbers"),
    ],
)
def test_identifier_columns(series):
    assert is_identifier(series)


@pytest.mark.parametrize(
    "series",
    [
        pytest.param(AGES, id="age"),
        pytest.param(column(rng.integers(30_000, 90_000, 50), "income"), id="income"),
        pytest.param(column([0.5, 0.05, 1.5, 2.0] * 5, "dose"), id="decimals below one"),
        pytest.param(column(rng.integers(0, 40, 50), "phone_calls"), id="a count of calls"),
    ],
)
def test_measurement_columns(series):
    assert not is_identifier(series)


def test_identifier_and_ordinal_columns_get_no_outlier_check():
    ratings = column(
        [1] + [8, 9, 9, 10, 8, 9, 10, 9] * 10, "satisfaction"
    )  # the 1 is a real answer
    ids = column(list(range(1, 40)) + [100_000], "order_id")
    zips = column(["02134"] * 20 + ["99950"] + ["02139"] * 20, "zip_code")
    assert detect_outliers(frame(ratings, ids, zips)) == []


def test_measurements_are_still_checked():
    (issue,) = detect_outliers(frame(AGES))
    assert issue.count == 2


# --------------------------------------------------------------------------- cut-off data


def test_cutoffs_describe_the_usual_range_and_the_distribution():
    (issue,) = detect_outliers(frame(AGES))
    cutoffs = issue.cutoffs
    assert (cutoffs.lower_text, cutoffs.upper_text) == (
        str(int(cutoffs.lower)),
        str(int(cutoffs.upper)),
    )
    assert cutoffs.values == 200
    assert len(cutoffs.quantiles) == 201
    assert cutoffs.quantiles == sorted(cutoffs.quantiles)
    # Real data values only, so previews and caps never invent numbers.
    assert set(cutoffs.quantiles) <= {float(a) for a in AGES}
    assert (cutoffs.quantiles[0], cutoffs.quantiles[-1]) == (float(AGES.astype(int).min()), 250.0)
    assert (cutoffs.lower_pct, cutoffs.upper_pct) == (1.0, 99.0)
    assert cutoffs.percentiles_ok


def test_percentiles_need_enough_values():
    small = column([30, 32, 35, 36, 38, 40, 41, 43, 45, 47, 250], "age")
    (issue,) = detect_outliers(frame(small))
    assert not issue.cutoffs.percentiles_ok


# ------------------------------------------------------------------------------ the step


@pytest.mark.parametrize(
    "fields",
    [
        {"lower": 1, "upper_pct": 99},  # values and percentiles mixed
        {},  # no cut-off at all
        {"lower": 9, "upper": 1},  # reversed
        {"lower_pct": 60},  # lower percentile above the median
        {"upper_pct": 101},
    ],
)
def test_invalid_cutoffs_are_rejected(fields):
    with pytest.raises(ValidationError):
        FixOutliers(column="age", action="cap", **fields)


def test_percentile_cap_uses_real_values():
    df = frame(AGES)
    out = apply_steps(df, [FixOutliers(column="age", action="cap", lower_pct=1, upper_pct=99)])
    numbers = out["age"].astype(int)
    p1 = int(AGES.astype(int).quantile(0.01, interpolation="nearest"))
    p99 = int(AGES.astype(int).quantile(0.99, interpolation="nearest"))
    assert (numbers.min(), numbers.max()) == (p1, p99)
    assert set(out["age"]) <= set(AGES)  # whole numbers stay whole, no new values


def test_percentile_drop_rows():
    out = apply_steps(frame(AGES), [FixOutliers(column="age", action="drop_rows", upper_pct=99)])
    assert len(out) < len(AGES)
    assert "250" not in set(out["age"])


def test_one_sided_cut_offs_leave_the_other_side_alone():
    df = frame(column([-5, 10, 20, 30, 40, 900], "x"))
    upper_only = apply_steps(df, [FixOutliers(column="x", action="cap", upper=40)])
    assert upper_only["x"].tolist() == ["-5", "10", "20", "30", "40", "40"]
    lower_only = apply_steps(df, [FixOutliers(column="x", action="cap", lower=0)])
    assert lower_only["x"].tolist() == ["0", "10", "20", "30", "40", "900"]


def test_own_values_are_written_in_the_columns_style():
    df = frame(column([10, 20, 30, 900], "x"))
    out = apply_steps(df, [FixOutliers(column="x", action="cap", lower=0, upper=100)])
    assert out["x"].tolist() == ["10", "20", "30", "100"]


def test_api_accepts_percentile_steps(client):
    csv = ("age\n" + "\n".join(AGES) + "\n").encode()
    step = {"op": "fix_outliers", "column": "age", "action": "cap", "lower_pct": 1, "upper_pct": 99}
    res = client.post(
        "/transform", files={"file": ("d.csv", csv, "text/csv")}, data={"steps": json.dumps([step])}
    )
    assert res.status_code == 200
    assert "250" not in res.text.splitlines()


def test_percentiles_come_from_the_column_as_uploaded():
    # Another fix drops the two highest ages first; the 99th percentile must not shift.
    ages = column(list(range(1, 199)) + [5000, 6000], "age")
    other = column(["x"] * 198 + ["drop", "drop"], "k")
    steps = [
        FixOutliers(column="age", action="drop_rows", lower=0, upper=4000),
        FixOutliers(column="age", action="cap", upper_pct=99),
    ]
    out = apply_steps(frame(ages, other), steps)
    # 99th percentile of all 200 values is 198; of the 198 left after the drop it would be 196.
    assert out["age"].astype(int).max() == 198
    assert len(out) == 198


def test_detail_lists_each_outlying_value_once():
    ages = column(list(range(30, 50)) + [120, 120, 150], "age")
    (issue,) = detect_outliers(frame(ages))
    assert issue.detail == "Found 150, 120"
