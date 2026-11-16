"""Text that stands for a missing value ("N/A", "NULL") counts as missing, but is kept unless
the user chooses a fix."""

import json

from app.detectors import run_detectors
from app.detectors.missing import detect_missing
from app.models import ClearPlaceholders, DropNullRows, FillNulls, FixTypeMismatch
from app.placeholders import placeholder_mask
from app.transform import apply_steps

# Placeholders in any case, with stray spaces, alongside a truly empty cell.
SCORES = "name,score\nA,10\nB,NULL\nC,null\nD, n/a \nE,N/A\nF,#N/A\nG,\nH,20\nI,30\n"


def _missing(df, column):
    return next(i for i in detect_missing(df) if i.columns == [column])


# --------------------------------------------------------------------------- recognizing


def test_common_placeholders_are_recognized_in_any_case(make_df):
    df = make_df(SCORES)
    assert placeholder_mask(df["score"]).tolist() == [
        False, True, True, True, True, True, False, False, False,
    ]  # fmt: skip


def test_cells_of_only_spaces_are_placeholders(make_df):
    df = make_df("a,b\nx,1\n   ,2\n")
    assert placeholder_mask(df["a"]).tolist() == [False, True]


def test_na_is_a_placeholder_in_number_columns(make_df):
    df = make_df("age\n30\nNA\n41\nnan\nunknown\n52\n")
    assert placeholder_mask(df["age"]).tolist() == [False, True, False, True, True, False]


def test_na_and_nan_are_kept_as_values_in_text_columns(make_df):
    # Namibia's country code, and a name.
    df = make_df("country,name\nGhana,Ama\nNA,Nan\nKenya,Wanjiru\n")
    assert not placeholder_mask(df["country"]).any()
    assert not placeholder_mask(df["name"]).any()


def test_words_that_can_mean_zero_are_not_placeholders(make_df):
    df = make_df("children\n2\nnone\n1\n-\n3\nnil\n")
    assert not placeholder_mask(df["children"]).any()


def test_null_is_a_placeholder_even_in_text_columns(make_df):
    df = make_df("city\nAccra\nNULL\nLagos\n")
    assert placeholder_mask(df["city"]).tolist() == [False, True, False]


# ------------------------------------------------------------------------------ detecting


def test_placeholders_count_as_missing(make_df):
    issue = _missing(make_df(SCORES), "score")
    assert issue.count == 6  # five placeholders and one empty cell
    assert issue.detail.startswith("Counts ")
    assert issue.detail.startswith('Counts "NULL", "null", " n/a " as missing.')


def test_placeholders_dont_stop_a_column_being_numeric(make_df):
    # Mostly placeholders: the numbers are what's left, so mean and median are offered.
    df = make_df("score\n10\nN/A\nN/A\nN/A\n20\nNULL\n")
    ids = {f.id for f in _missing(df, "score").fixes}
    assert {"fill_mean", "fill_median", "clear_placeholders"} <= ids


def test_clearing_is_offered_only_when_there_are_placeholders(make_df):
    df = make_df("score,k\n10,a\n,b\n20,c\n")
    assert "clear_placeholders" not in {f.id for f in _missing(df, "score").fixes}


def test_clearing_is_recommended_when_no_value_fits(make_df):
    # Free text: no single fill value fits, but empty cells beat "N/A" text.
    rows = "".join(f"note {i}\n" for i in range(10))
    issue = _missing(make_df("note\n" + rows + "N/A\n"), "note")
    (recommended,) = [f.id for f in issue.fixes if f.recommended]
    assert recommended == "clear_placeholders"


def test_other_detectors_see_placeholders_as_empty(make_df):
    # Without this, "N/A" would be "text in a number column" and "n/a" vs "N/A" inconsistent.
    df = make_df("age,city\n30,Accra\nN/A,n/a\n41,N/A\n52,Accra\n27,Accra\n")
    categories = {i.category for i in run_detectors(df)}
    assert categories == {"missingness"}


# ------------------------------------------------------------------------------- fixing


def test_leaving_placeholders_returns_them_unchanged(make_df):
    df = make_df(SCORES)
    assert apply_steps(df, []).equals(df)


def test_filling_covers_placeholders(make_df):
    out = apply_steps(make_df(SCORES), [FillNulls(column="score", strategy="median")])
    assert out["score"].tolist() == ["10"] + ["20"] * 6 + ["20", "30"]


def test_dropping_rows_covers_placeholders(make_df):
    out = apply_steps(make_df(SCORES), [DropNullRows(column="score")])
    assert out["name"].tolist() == ["A", "H", "I"]


def test_clear_placeholders_makes_them_empty(make_df):
    out = apply_steps(make_df(SCORES), [ClearPlaceholders(column="score")])
    assert out["score"].isna().tolist() == [False] + [True] * 6 + [False, False]


def test_clear_placeholders_leaves_other_columns_alone(make_df):
    df = make_df("a,b\n1,N/A\nN/A,2\n")
    out = apply_steps(df, [ClearPlaceholders(column="a")])
    assert out["a"].isna().tolist() == [False, True]
    assert out["b"].tolist() == ["N/A", "2"]


def test_type_mismatch_fixes_leave_placeholders_alone(make_df):
    df = make_df("age\n30\nN/A\ntwenty\n41\n52\n")
    out = apply_steps(df, [FixTypeMismatch(column="age", action="drop_rows")])
    assert out["age"].tolist() == ["30", "N/A", "41", "52"]


def test_mean_ignores_placeholders(make_df):
    out = apply_steps(make_df("x\n10\nNA\n20\n"), [FillNulls(column="x", strategy="mean")])
    assert out["x"].tolist() == ["10", "15", "20"]


# ------------------------------------------------------------------------------------ API


def _upload(raw: bytes) -> dict:
    return {"file": ("d.csv", raw, "text/csv")}


def test_untouched_placeholders_survive_a_round_trip(client):
    raw = b"name,score\nA,10\nB,NULL\nC,N/A\nD,\n"
    steps = json.dumps([{"op": "fill_nulls", "column": "name", "strategy": "mode"}])
    res = client.post("/transform", files=_upload(raw), data={"steps": steps})
    assert res.content == raw


def test_clear_placeholders_over_the_api(client):
    raw = b"name,score\nA,10\nB,NULL\nC,N/A\nD,\n"
    steps = json.dumps([{"op": "clear_placeholders", "column": "score"}])
    res = client.post("/transform", files=_upload(raw), data={"steps": steps})
    assert res.content == b"name,score\nA,10\nB,\nC,\nD,\n"
