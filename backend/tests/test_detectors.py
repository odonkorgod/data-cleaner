import pandas as pd

from app.detectors.duplicates import detect_duplicates
from app.detectors.missing import detect_missing


def test_missing_reports_one_issue_per_affected_column(messy_df):
    issues = detect_missing(messy_df)
    assert {i.id for i in issues} == {"missing:name", "missing:age"}
    assert all(i.count == 1 for i in issues)


def test_missing_offers_mean_and_median_only_for_numeric_columns(messy_df):
    by_id = {i.id: i for i in detect_missing(messy_df)}
    numeric_fixes = {f.id for f in by_id["missing:age"].fixes}
    text_fixes = {f.id for f in by_id["missing:name"].fixes}

    assert {"fill_mean", "fill_median"} <= numeric_fixes
    assert not {"fill_mean", "fill_median"} & text_fixes
    assert {"drop_rows", "fill_mode", "fill_constant", "leave"} <= text_fixes


def test_missing_constant_fix_requires_a_value(messy_df):
    issue = detect_missing(messy_df)[0]
    constant = next(f for f in issue.fixes if f.id == "fill_constant")
    assert constant.needs_value is True


def test_missing_samples_show_only_affected_rows(messy_df):
    issue = next(i for i in detect_missing(messy_df) if i.id == "missing:age")
    assert len(issue.samples) == 1
    assert issue.samples[0]["name"] == "Linus"
    assert issue.samples[0]["age"] is None


def test_missing_returns_nothing_for_clean_data():
    assert detect_missing(pd.DataFrame({"a": [1, 2, 3]})) == []


def test_duplicates_counts_only_extra_copies(messy_df):
    (issue,) = detect_duplicates(messy_df)
    assert issue.count == 1
    # Samples show every copy in the group so the user can see what matches.
    assert len(issue.samples) == 2


def test_duplicates_returns_nothing_when_rows_are_unique():
    assert detect_duplicates(pd.DataFrame({"a": [1, 2, 3]})) == []


def test_mean_and_median_need_every_present_value_to_be_a_number(make_df):
    df = make_df("code,n\n12,1\nAB,2\n,3\n")
    (issue,) = detect_missing(df)
    assert not {"fill_mean", "fill_median"} & {f.id for f in issue.fixes}


def test_entirely_empty_column_is_not_offered_mean_or_median(make_df):
    df = make_df("a,b\n1,\n2,\n")
    (issue,) = detect_missing(df)
    assert not {"fill_mean", "fill_median"} & {f.id for f in issue.fixes}
