import pandas as pd
import pytest

from app.models import DropDuplicates, DropNullRows, FillNulls
from app.transform import TransformError, apply_steps


def test_fill_nulls_with_median(messy_df):
    out = apply_steps(messy_df, [FillNulls(column="age", strategy="median")])
    assert out["age"].isna().sum() == 0
    # median of 36, 45, 45, 30 is 40.5
    assert out.loc[3, "age"] == "40.5"


def test_fill_nulls_with_mean(make_df):
    df = make_df("x,y\n1,a\n3,b\n,c\n")
    out = apply_steps(df, [FillNulls(column="x", strategy="mean")])
    # A whole-number result in an integer column is written without ".0".
    assert out["x"].tolist() == ["1", "3", "2"]


def test_whole_number_fill_keeps_decimals_when_the_column_uses_them(make_df):
    df = make_df("x,y\n1.0,a\n3.0,b\n,c\n")
    out = apply_steps(df, [FillNulls(column="x", strategy="mean")])
    assert out["x"].tolist() == ["1.0", "3.0", "2.0"]


def test_fill_nulls_with_mode(messy_df):
    out = apply_steps(messy_df, [FillNulls(column="name", strategy="mode")])
    assert out["name"].isna().sum() == 0
    assert out.loc[4, "name"] == "Grace"


def test_fill_nulls_with_constant(messy_df):
    out = apply_steps(messy_df, [FillNulls(column="name", strategy="constant", value="Unknown")])
    assert out.loc[4, "name"] == "Unknown"


def test_numeric_constant_is_written_as_typed(messy_df):
    out = apply_steps(messy_df, [FillNulls(column="age", strategy="constant", value="0")])
    assert out.loc[3, "age"] == "0"


def test_numeric_column_rejects_text_constant(messy_df):
    with pytest.raises(TransformError, match="must be a number"):
        apply_steps(messy_df, [FillNulls(column="age", strategy="constant", value="n/a")])


def test_constant_without_value_is_rejected(messy_df):
    with pytest.raises(TransformError, match="value is required"):
        apply_steps(messy_df, [FillNulls(column="name", strategy="constant")])


def test_mean_of_text_column_is_rejected(messy_df):
    with pytest.raises(TransformError, match="non-numeric"):
        apply_steps(messy_df, [FillNulls(column="name", strategy="mean")])


def test_drop_null_rows(messy_df):
    out = apply_steps(messy_df, [DropNullRows(column="age")])
    assert len(out) == len(messy_df) - 1
    assert out["age"].isna().sum() == 0


def test_drop_duplicates_keep_first_and_last(make_df):
    df = make_df("a,b\n1,x\n1,x\n2,y\n")
    assert len(apply_steps(df, [DropDuplicates(keep="first")])) == 2
    assert len(apply_steps(df, [DropDuplicates(keep="last")])) == 2


def test_unknown_column_gives_a_clear_error(messy_df):
    with pytest.raises(TransformError, match="'nope' does not exist"):
        apply_steps(messy_df, [DropNullRows(column="nope")])


def test_steps_run_in_fixed_order_not_submission_order(make_df):
    # Row 1 only becomes a duplicate of row 0 *after* its null is filled with 1.
    # If drop_duplicates ran first (as submitted), both rows would survive.
    df = make_df("a,b\n1,x\n,x\n")
    steps = [DropDuplicates(keep="first"), FillNulls(column="a", strategy="constant", value="1")]
    out = apply_steps(df, steps)
    assert len(out) == 1


def test_apply_steps_does_not_mutate_the_input(messy_df):
    before = messy_df.copy()
    apply_steps(messy_df, [FillNulls(column="age", strategy="mean"), DropDuplicates()])
    pd.testing.assert_frame_equal(messy_df, before)


def test_no_steps_returns_same_data(messy_df):
    out = apply_steps(messy_df, [])
    pd.testing.assert_frame_equal(out, messy_df)
