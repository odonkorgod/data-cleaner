"""Invalid values: suggested rules, detection, the fix, and how they interact with other fixes."""

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from app.detectors.invalid import detect_invalid, number_summaries
from app.detectors.outliers import detect_outliers
from app.models import FillNulls, FixInvalid, FixOutliers
from app.rules import name_rule, name_words, sign_rule, suggested_rule
from app.transform import apply_steps


def column(values, name: str) -> pd.Series:
    return pd.Series([None if v is None else str(v) for v in values], dtype="str", name=name)


def frame(*columns: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({c.name: c for c in columns})


NUMBERS = pd.Series([1.0, 50.0, 80.0])


# ---------------------------------------------------------------------- rules from names


def test_name_words_split_snake_and_camel_case():
    assert name_words("orderID") == ["order", "id"]
    assert name_words("age_in_days") == ["age", "in", "days"]
    assert name_words("customerAge2") == ["customer", "age", "2"]


@pytest.mark.parametrize(
    "name, bounds",
    [
        ("age", (0, 120)),
        ("customerAge", (0, 120)),
        ("average_age", (0, 120)),
        ("discount_pct", (0, 100)),
        ("birth_month", (1, 12)),
        ("day", (1, 31)),
        ("hour", (0, 23)),
        ("minute", (0, 59)),
        ("Latitude", (-90, 90)),
        ("lng", (-180, 180)),
        ("unit_price", (0, None)),
        ("net_weight", (0, None)),
        ("qty", (0, None)),
    ],
)
def test_names_with_rules(name, bounds):
    rule = name_rule(name, NUMBERS)
    assert (rule.min, rule.max) == bounds
    assert rule.source == "name"


@pytest.mark.parametrize(
    "name",
    [
        "age_days",  # a duration, not an age in years
        "account_age_in_months",
        "stage",
        "page_views",
        "usage",
        "pct_change",  # changes can be negative
        "price_change",
        "months_active",
        "day_of_week",
        "hours_worked",
        "years_experience",
        "account_balance",
        "income",
        "temperature",
    ],
)
def test_names_without_rules(name):
    assert name_rule(name, NUMBERS) is None


def test_percent_columns_on_a_zero_to_one_scale():
    rule = name_rule("pct", pd.Series([0.1, 0.25, 0.9, 1.0] * 5))
    assert (rule.min, rule.max) == (0, 1)


def test_year_rule_ends_next_year():
    rule = name_rule("birth_year", NUMBERS)
    assert rule.min == 1900 and rule.max == pd.Timestamp.today().year + 1


# ---------------------------------------------------------------------- rules from data


def test_rare_negatives_look_like_sign_errors():
    rule = sign_rule(pd.Series([float(v) for v in range(1, 1000)] + [-5.0]))
    assert (rule.min, rule.max, rule.source) == (0, None, "data")
    assert "1 of 1,000" in rule.reason


def test_common_negatives_are_real_data():
    assert sign_rule(pd.Series([-5.0, 3.0, 8.0, -1.0] * 10)) is None


def test_too_few_values_for_a_sign_rule():
    assert sign_rule(pd.Series([1.0] * 10 + [-1.0])) is None


def test_ids_and_text_get_no_rule():
    assert suggested_rule(column([-1, 2, 3] * 10, "store_id")) is None
    assert suggested_rule(column(["a", "b"] * 10, "age_group")) is None


# ------------------------------------------------------------------------------ detector


AGES = column([25, 31, 44, -4, 150, 52, 38, None], "age")


def test_detector_reports_values_breaking_the_rule():
    (issue,) = detect_invalid(frame(AGES))
    assert issue.category == "invalid"
    assert issue.count == 2
    assert issue.detail == "Found 150, -4"  # furthest outside the rule first
    assert (issue.rule.min, issue.rule.max, issue.rule.source) == (0, 120, "name")
    clear = next(f for f in issue.fixes if f.id == "clear")
    assert clear.recommended
    assert clear.step == {
        "op": "fix_invalid",
        "column": "age",
        "min": 0,
        "max": 120,
        "action": "clear",
    }


def test_valid_columns_have_no_issue():
    assert detect_invalid(frame(column([25, 31, 44], "age"))) == []


def test_invalid_values_are_not_also_outliers():
    ages = column([30, 32, 35, 36, 38, 40, 41, 43, 45, 47, -40, 999], "age")
    assert detect_outliers(frame(ages)) == []
    (issue,) = detect_invalid(frame(ages))
    assert issue.count == 2


def test_number_summaries_cover_number_columns_but_not_ids():
    df = frame(AGES, column([1, 2, 3, 4, 5, 6, 7, 8], "order_id"), column(list("abcdefgh"), "name"))
    summaries = number_summaries(df)
    assert list(summaries) == ["age"]
    assert summaries["age"].values == 7
    assert len(summaries["age"].quantiles) == 201


# ------------------------------------------------------------------------------- the fix


@pytest.mark.parametrize("fields", [{}, {"min": 10, "max": 1}])
def test_invalid_rules_are_rejected(fields):
    with pytest.raises(ValidationError):
        FixInvalid(column="age", action="clear", **fields)


def test_clear_empties_the_cells_and_drop_removes_the_rows():
    df = frame(AGES)
    cleared = apply_steps(df, [FixInvalid(column="age", action="clear", min=0, max=120)])
    assert cleared["age"].isna().tolist() == [False, False, False, True, True, False, False, True]
    dropped = apply_steps(df, [FixInvalid(column="age", action="drop_rows", min=0, max=120)])
    assert len(dropped) == len(df) - 2


def test_one_sided_rule():
    out = apply_steps(frame(AGES), [FixInvalid(column="age", action="clear", min=18)])
    assert out["age"].isna().sum() == 2  # -4 and the empty cell; 150 is allowed
    assert "150" in set(out["age"])


def test_cleared_values_are_filled_by_a_missing_value_fix():
    df = frame(column([20, 30, -5, 40, 50], "age"))
    steps = [
        FillNulls(column="age", strategy="median"),
        FixInvalid(column="age", action="clear", min=0),
    ]
    assert apply_steps(df, steps)["age"].tolist() == ["20", "30", "35", "40", "50"]


def test_percentile_cutoffs_leave_out_invalid_values():
    valid = list(range(1, 101))
    ages = column(valid + [-500, -400], "age")  # two impossible ages at the bottom
    out = apply_steps(frame(ages), [FixOutliers(column="age", action="cap", lower_pct=1)])
    # The 1st percentile of the valid ages (2), not one of the negatives (-400).
    expected = pd.Series(valid).quantile(0.01, interpolation="nearest")
    assert out["age"].astype(int).min() == expected == 2


def test_api_round_trip_with_a_users_own_rule(client):
    csv = b"age,k\n4,a\n25,b\n31,c\n44,d\n"
    body = client.post("/analyze", files={"file": ("d.csv", csv, "text/csv")}).json()
    assert "age" in body["numbers"]
    step = {"op": "fix_invalid", "column": "age", "action": "clear", "min": 18}
    res = client.post(
        "/transform", files={"file": ("d.csv", csv, "text/csv")}, data={"steps": json.dumps([step])}
    )
    assert res.text.splitlines()[1] == ",a"  # age 4 cleared: customers are 18+
