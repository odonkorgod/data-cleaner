"""Inconsistent spellings, type mismatches and outliers: detection, then the matching fixes."""

import pandas as pd
import pytest
from pydantic import ValidationError

from app.detectors.inconsistent import detect_inconsistent
from app.detectors.outliers import detect_outliers
from app.detectors.type_mismatch import detect_type_mismatch
from app.models import (
    DropDuplicates,
    FillNulls,
    FixOutliers,
    FixTypeMismatch,
    StandardizeValues,
)
from app.transform import apply_steps
from app.values import canonical_spellings, outlier_range

CITIES = "city,n\nNew York,1\nnew york,2\nNew York,3\n NEW YORK,4\nParis,5\nparis,6\nParis,7\n"
# Ten ordinary ages and one typo.
AGE_VALUES = ["30", "32", "35", "36", "38", "40", "41", "43", "45", "47", "250"]
AGES = "age\n" + "".join(f"{a}\n" for a in AGE_VALUES)


# ----------------------------------------------------------------------- inconsistent data


def test_canonical_spelling_is_the_most_common_one():
    mapping = canonical_spellings(pd.Series(["b", "B", "B", "a", " A "]))
    # "B" is most common; "a" and " A " tie, so the first seen wins.
    assert mapping == {"b": "B", " A ": "a"}


def test_inconsistent_counts_cells_that_would_change(make_df):
    (issue,) = detect_inconsistent(make_df(CITIES))
    assert issue.category == "inconsistent"
    assert issue.columns == ["city"]
    assert issue.count == 3  # "new york", " NEW YORK", "paris"
    assert '"New York"' in issue.detail and "1 more value" in issue.detail


def test_inconsistent_ignores_number_columns_and_consistent_text(make_df):
    assert detect_inconsistent(make_df("a,b\n1,x\n2,y\n")) == []


def test_standardize_rewrites_variants_only(make_df):
    out = apply_steps(make_df(CITIES), [StandardizeValues(column="city")])
    assert out["city"].tolist() == ["New York"] * 4 + ["Paris"] * 3


def test_standardize_lets_duplicates_be_caught(make_df):
    df = make_df("name,team\nAda,Red\nada ,Red\n")
    out = apply_steps(df, [DropDuplicates(), StandardizeValues(column="name")])
    assert len(out) == 1


# -------------------------------------------------------------------------- type mismatch


def test_type_mismatch_flags_text_in_a_mostly_numeric_column(make_df):
    df = make_df("age\n30\n41\nunknown\n52\n27\n")
    (issue,) = detect_type_mismatch(df)
    assert issue.category == "type_mismatch"
    assert issue.count == 1
    assert '"unknown"' in issue.detail


def test_type_mismatch_ignores_text_columns_with_a_few_numbers(make_df):
    assert detect_type_mismatch(make_df("code\nAB\nCD\n12\nEF\n")) == []


def test_type_mismatch_clear_and_drop(make_df):
    df = make_df("age,name\n30,a\nn/a,b\n52,c\n")
    cleared = apply_steps(df, [FixTypeMismatch(column="age", action="clear")])
    assert cleared["age"].isna().tolist() == [False, True, False]
    dropped = apply_steps(df, [FixTypeMismatch(column="age", action="drop_rows")])
    assert dropped["name"].tolist() == ["a", "c"]


# ------------------------------------------------------------------------------ outliers


def test_outlier_range_snaps_to_real_values(make_df):
    assert outlier_range(make_df(AGES)["age"]) == (30.0, 47.0)


def test_outliers_detected_with_usual_range(make_df):
    (issue,) = detect_outliers(make_df(AGES))
    assert issue.category == "outliers"
    assert issue.count == 1
    assert issue.detail == "Usual range 30 to 47, found 250"
    cap = next(f for f in issue.fixes if f.id == "cap")
    assert cap.step == {
        "op": "fix_outliers", "column": "age", "lower": 30.0, "upper": 47.0, "action": "cap"
    }


def test_outliers_need_enough_values_and_some_spread(make_df):
    assert detect_outliers(make_df("x\n1\n2\n900\n")) == []
    assert detect_outliers(make_df("x\n" + "5\n" * 10 + "6\n")) == []


def test_cap_uses_the_columns_own_formatting(make_df):
    df = make_df("price\n" + "".join(f"{p}\n" for p in ["1.50", "1.75", "2.00"] * 3) + "99.00\n")
    out = apply_steps(df, [FixOutliers(column="price", lower=1.5, upper=2.0, action="cap")])
    assert out["price"].iloc[-1] == "2.00"


def test_outlier_fixes_leave_text_and_empty_cells_alone(make_df):
    df = make_df("x,k\n1,a\n500,b\n,c\noops,d\n")
    capped = apply_steps(df, [FixOutliers(column="x", lower=1, upper=10, action="cap")])
    assert capped["x"].tolist()[:2] == ["1", "10"]
    assert capped["x"].iloc[3] == "oops"
    dropped = apply_steps(df, [FixOutliers(column="x", lower=1, upper=10, action="drop_rows")])
    assert dropped["k"].tolist() == ["a", "c", "d"]


def test_outliers_are_handled_before_mean_fill(make_df):
    df = make_df("x,k\n1,a\n3,b\n,c\n1000,d\n")
    steps = [
        FillNulls(column="x", strategy="mean"),
        FixOutliers(column="x", lower=1, upper=3, action="drop_rows"),
    ]
    assert apply_steps(df, steps)["x"].tolist() == ["1", "3", "2"]


def test_outlier_bounds_must_be_ordered():
    with pytest.raises(ValidationError):
        FixOutliers(column="x", lower=5, upper=1, action="cap")


# ------------------------------------------------------------------------------------ API


def test_analyze_groups_every_issue_into_a_category(client):
    # An outlier (250), stray text in a number column (n/a), and a spelling variant (rome).
    rows = [f"{age},Rome" for age in AGE_VALUES] + ["n/a,rome"]
    csv = ("age,city\n" + "\n".join(rows) + "\n").encode()
    body = client.post("/analyze", files={"file": ("d.csv", csv, "text/csv")}).json()
    assert {i["category"] for i in body["issues"]} == {"outliers", "type_mismatch", "inconsistent"}
