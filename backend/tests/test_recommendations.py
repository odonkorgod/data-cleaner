"""Column kinds, distribution shape, and the fill recommendation built on them."""

import numpy as np
import pandas as pd
import pytest

from app.detectors.missing import detect_missing, recommend_fill
from app.models import FillNulls, FixTypeMismatch
from app.transform import apply_steps
from app.values import column_kind, distribution_shape, is_categorical

rng = np.random.default_rng(7)


def column(values, name="x", blanks=2) -> pd.Series:
    """A column as read_csv produces it: text cells, None for empty ones."""
    return pd.Series([str(v) for v in values] + [None] * blanks, dtype="str", name=name)


NORMAL = column(np.round(rng.normal(170, 8, 300), 1), "height_cm")
SKEWED = column(np.round(rng.lognormal(10.8, 0.5, 300)).astype(int), "income")
SCORES = column(rng.integers(1, 11, 200), "satisfaction")
CITIES = column(rng.choice(["Accra", "Kumasi", "Tamale"], 60), "city")


# --------------------------------------------------------------------------- column kinds


@pytest.mark.parametrize(
    "series, kind",
    [
        pytest.param(SCORES, "ordinal", id="satisfaction 1-10"),
        pytest.param(column(rng.integers(1, 6, 40)), "ordinal", id="likert 1-5"),
        pytest.param(column(rng.integers(0, 11, 100)), "ordinal", id="nps 0-10"),
        pytest.param(column(rng.integers(0, 2, 30)), "ordinal", id="binary 0/1"),
        pytest.param(CITIES, "nominal", id="text categories"),
        pytest.param(NORMAL, "continuous", id="measurements"),
        pytest.param(SKEWED, "continuous", id="unique incomes are not IDs"),
        pytest.param(column(rng.integers(18, 80, 200)), "continuous", id="ages span > 10"),
        pytest.param(column(range(1000, 1050), "row"), "unique", id="sequential numbers"),
        pytest.param(
            column(rng.permutation(10**8)[:50] + 10**7, "account_number"),
            "unique",
            id="unique numbers named like an ID",
        ),
        pytest.param(column([f"Person {i}" for i in range(40)]), "unique", id="names"),
        pytest.param(column([], blanks=3), "empty", id="empty"),
    ],
)
def test_column_kind(series, kind):
    assert column_kind(series) == kind


def test_ordinal_needs_values_to_repeat():
    # Ten different whole numbers in ten rows could be anything, not a scale.
    assert column_kind(column(range(1, 11))) == "continuous"


def test_stray_text_does_not_hide_an_ordinal_scale():
    scores = column(list(rng.integers(1, 6, 40)) + ["n/a", "unknown"])
    assert column_kind(scores) == "ordinal"


def test_is_categorical():
    assert is_categorical(SCORES) and is_categorical(CITIES)
    assert not is_categorical(NORMAL) and not is_categorical(SKEWED)
    assert not is_categorical(column([f"note {i}" for i in range(30)]))


# ------------------------------------------------------------------------- distribution shape


def test_shape_needs_enough_distinct_values():
    assert distribution_shape(pd.Series(rng.normal(size=19))) is None
    assert distribution_shape(pd.Series([5.0] * 50)) is None


def test_shape_tells_normal_from_skewed_and_flat():
    assert distribution_shape(pd.Series(rng.normal(size=500))).roughly_normal
    assert not distribution_shape(pd.Series(rng.lognormal(size=500))).roughly_normal
    assert not distribution_shape(pd.Series(rng.uniform(size=500))).roughly_normal


# --------------------------------------------------------------------------- recommendations


def test_normal_numbers_get_the_mean():
    advice = recommend_fill(NORMAL)
    assert advice.fix_id == "fill_mean"
    assert "normal" in advice.reason


def test_skewed_numbers_get_the_median():
    advice = recommend_fill(SKEWED)
    assert advice.fix_id == "fill_median"
    assert "Skewed to the right" in advice.reason


def test_flat_numbers_get_the_median():
    advice = recommend_fill(column(rng.integers(18, 80, 300), "age"))
    assert advice.fix_id == "fill_median"
    assert "Not bell-shaped" in advice.reason


def test_few_numbers_get_the_median():
    advice = recommend_fill(column([12.5, 14.0, 13.2, 19.9, 11.1]))
    assert advice.fix_id == "fill_median"
    assert "Too few numbers (5)" in advice.reason


def test_ordinal_scores_get_the_mode():
    advice = recommend_fill(SCORES)
    assert advice.fix_id == "fill_mode"
    assert "1–10 scale" in advice.reason


def test_binary_values_get_the_mode():
    advice = recommend_fill(column([0, 1, 1, 0, 1, 1]))
    assert advice.fix_id == "fill_mode"
    assert "two values (0 and 1)" in advice.reason


def test_text_categories_get_the_mode():
    advice = recommend_fill(CITIES)
    assert advice.fix_id == "fill_mode"
    assert "3 distinct values" in advice.reason


def test_ids_and_free_text_are_left_alone():
    assert recommend_fill(column(range(1, 101), "customer_id")).fix_id == "leave"
    assert recommend_fill(column([f"note {i}" for i in range(30)])).fix_id == "leave"


def test_empty_column_gets_no_recommendation():
    assert recommend_fill(column([], blanks=4)) is None


# ------------------------------------------------------------------------ in the issue report


def test_missing_issue_marks_exactly_the_recommended_fix():
    heights = np.round(rng.normal(170, 8, len(SCORES) - 2), 1)
    df = pd.DataFrame({"satisfaction": SCORES, "height_cm": column(heights, "height_cm")})
    issues = {i.columns[0]: i for i in detect_missing(df)}

    for column_name, expected in [("satisfaction", "fill_mode"), ("height_cm", "fill_mean")]:
        issue = issues[column_name]
        assert [f.id for f in issue.fixes if f.recommended] == [expected]
        assert issue.detail == recommend_fill(df[column_name]).reason


def test_analyze_returns_recommendations(client):
    csv = b"score,k\n" + b"".join(f"{s},a\n".encode() for s in rng.integers(1, 6, 30)) + b",b\n"
    body = client.post("/analyze", files={"file": ("d.csv", csv, "text/csv")}).json()
    (issue,) = [i for i in body["issues"] if i["category"] == "missingness"]
    assert [f["id"] for f in issue["fixes"] if f["recommended"]] == ["fill_mode"]
    assert "1–5 scale" in issue["detail"]


# ----------------------------------------------- mean/median work around stray text


def test_mean_and_median_are_offered_despite_stray_text(make_df):
    df = make_df("age,k\n30,a\n40,b\nunknown,c\n50,d\n60,e\n,f\n")
    (issue,) = [i for i in detect_missing(df) if i.columns == ["age"]]
    assert {"fill_mean", "fill_median"} <= {f.id for f in issue.fixes}


def test_mean_fill_ignores_stray_text(make_df):
    df = make_df("age,k\n30,a\n40,b\nunknown,c\n50,d\n60,e\n,f\n")
    out = apply_steps(df, [FillNulls(column="age", strategy="mean")])
    assert out["age"].tolist() == ["30", "40", "unknown", "50", "60", "45"]


def test_clearing_stray_text_then_filling_fills_those_cells_too(make_df):
    df = make_df("age,k\n30,a\n40,b\nunknown,c\n50,d\n60,e\n,f\n")
    steps = [
        FillNulls(column="age", strategy="median"),
        FixTypeMismatch(column="age", action="clear"),
    ]
    assert apply_steps(df, steps)["age"].tolist() == ["30", "40", "45", "50", "60", "45"]


# ------------------------------------------- whole numbers written with zero decimals

ZERO_DECIMALS = column(
    [f"{s}.0" for s in rng.integers(1, 11, 60)]  # "7.0"
    + [f"{s}.00" for s in rng.integers(1, 11, 20)]  # "7.00"
    + [f"{s}.0000" for s in rng.integers(1, 11, 20)],  # "7.0000"
    "satisfaction",
)


def test_zero_decimal_scores_are_an_ordinal_scale():
    assert column_kind(ZERO_DECIMALS) == "ordinal"
    assert is_categorical(ZERO_DECIMALS)


def test_mixed_integer_and_zero_decimal_scores_are_one_scale():
    mixed = column(
        [str(s) for s in rng.integers(1, 6, 30)] + [f"{s}.0" for s in rng.integers(1, 6, 30)]
    )
    assert column_kind(mixed) == "ordinal"
    assert "1–5 scale" in recommend_fill(mixed).reason


def test_zero_decimal_scores_get_the_mode_and_a_clean_scale_label():
    advice = recommend_fill(ZERO_DECIMALS)
    assert advice.fix_id == "fill_mode"
    assert "1–10 scale" in advice.reason


def test_real_decimals_are_not_an_ordinal_scale():
    assert column_kind(column([f"{s}.5" for s in rng.integers(1, 6, 40)])) == "continuous"


def test_mode_counts_differently_written_numbers_as_one_value(make_df):
    # 7 appears three times (written 3 ways); "8" appears twice as identical text.
    df = make_df("score,k\n7,a\n7.0,b\n8,c\n8,d\n7.00,e\n3,f\n,g\n")
    out = apply_steps(df, [FillNulls(column="score", strategy="mode")])
    assert out["score"].iloc[-1] == "7"


def test_mode_uses_the_numbers_most_common_spelling(make_df):
    df = make_df("score,k\n7.0,a\n7.0,b\n7,c\n2,d\n,e\n")
    out = apply_steps(df, [FillNulls(column="score", strategy="mode")])
    assert out["score"].iloc[-1] == "7.0"


def test_mode_of_text_columns_is_unchanged(make_df):
    df = make_df("city,k\nAccra,a\nTamale,b\nAccra,c\n,d\n")
    out = apply_steps(df, [FillNulls(column="city", strategy="mode")])
    assert out["city"].iloc[-1] == "Accra"
