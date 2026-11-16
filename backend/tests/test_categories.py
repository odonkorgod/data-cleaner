"""Text categories: case styles and their guards, merge suggestions, and standardizing."""

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from app.categories import (
    MergeError,
    apply_case,
    case_style,
    group_values,
    standardize_mapping,
    suggest_merges,
    value_case,
)
from app.detectors.inconsistent import detect_inconsistent
from app.models import MAX_MERGES, StandardizeValues
from app.transform import TransformError, apply_steps


def column(*runs: tuple[str, int]) -> pd.Series:
    """("New York", 3), ("nyc", 1) -> a text column with those values repeated."""
    return pd.Series([v for v, n in runs for _ in range(n)], dtype="str", name="city")


# ------------------------------------------------------------------------------ case


@pytest.mark.parametrize(
    "value, kind",
    [
        ("NEW YORK", "upper"),
        ("new york", "lower"),
        ("New York", "title"),
        ("Bank of America", "title"),
        ("NYC Office", "title"),
        ("eBay", "mixed"),
        ("McDonald", "mixed"),
        ("O'Neil", "mixed"),
        ("nEW yORK", "inverted"),
        ("New york", "other"),
        ("42", None),
    ],
)
def test_value_case(value, kind):
    assert value_case(value) == kind


@pytest.mark.parametrize(
    "value, title",
    [
        ("new york", "New York"),
        ("NEW YORK", "New York"),  # all caps is shouting, not acronyms
        ("nEW yORK", "New York"),  # caps-lock typing
        ("  st.  louis ", "St. Louis"),  # spacing tidied
        ("they're open", "They're Open"),  # not "They'Re"
        ("bank of america", "Bank of America"),  # small words stay lowercase...
        ("the hague", "The Hague"),  # ...except at the start
        ("jean-luc", "Jean-Luc"),
        ("NYC office", "NYC Office"),  # acronym inside a value is kept
        ("USA", "USA"),  # short all-caps value is an acronym
        ("NASA", "NASA"),
        ("eBay", "eBay"),  # deliberate mixed case is never changed
        ("iPhone", "iPhone"),
        ("McDonald", "McDonald"),
        ("O'Neil", "O'Neil"),
    ],
)
def test_title_case_guards(value, title):
    assert apply_case(value, "title") == title


def test_upper_lower_and_keep():
    assert apply_case("New York", "upper") == "NEW YORK"
    assert apply_case("New York", "lower") == "new york"
    assert apply_case(" new  York ", "keep") == "new York"
    assert apply_case("eBay", "upper") == "eBay"


def test_case_style_is_the_most_common_by_cells():
    assert case_style(column(("Gold", 3), ("SILVER", 2), ("bronze", 1))) == "title"
    assert case_style(column(("GOLD", 3), ("Silver", 2))) == "upper"


def test_case_style_ignores_mixed_case_and_values_without_letters():
    assert case_style(column(("eBay", 5), ("gold", 1))) == "lower"
    assert case_style(column(("42", 5), ("eBay", 2))) == "keep"


def test_case_style_ties_prefer_title_case():
    assert case_style(column(("Gold", 2), ("SILVER", 2))) == "title"


# ----------------------------------------------------------------------------- groups


def test_groups_join_case_and_spacing_variants_most_common_first():
    groups = group_values(column(("Accra", 2), ("New York", 3), ("new york ", 1)))
    assert list(groups) == ["new york", "accra"]
    assert groups["new york"].count == 4
    assert groups["new york"].spellings == [("New York", 3), ("new york ", 1)]


def test_a_deliberate_spelling_beats_a_more_common_one():
    groups = group_values(column(("EBAY", 5), ("eBay", 2)))
    assert groups["ebay"].display("upper") == "eBay"


# ------------------------------------------------------------------------ suggestions


def suggestions_for(*runs):
    return {k: s.target for k, s in suggest_merges(group_values(column(*runs))).items()}


@pytest.mark.parametrize(
    "rare, common",
    [
        ("New Yrok", "New York"),  # swapped letters in a 4-letter word
        ("Londn", "London"),
        ("Kumassi", "Kumasi"),
        ("Philadelpia", "Philadelphia"),
        ("Rio de Janiero", "Rio de Janeiro"),
        ("N.Y.C.", "NYC"),  # same letters, different punctuation
        ("St Louis", "St. Louis"),
    ],
)
def test_near_duplicates_are_suggested(rare, common):
    expected = {" ".join(rare.split()).casefold(): " ".join(common.split()).casefold()}
    assert suggestions_for((common, 5), (rare, 1)) == expected


@pytest.mark.parametrize(
    "a, b",
    [
        ("Austria", "Australia"),  # two edits: different countries
        ("Gold", "Bold"),  # short words: one letter is a different word
        ("Room 101", "Room 102"),  # different numbers
        ("Grade A", "Grade B"),
        ("Size XL", "Size L"),
        ("Male", "Female"),
        ("NYC", "New York"),  # abbreviations are for the user to merge
    ],
)
def test_different_values_are_not_suggested(a, b):
    assert suggestions_for((a, 5), (b, 1)) == {}


def test_suggestions_merge_rare_into_common_without_chains():
    # "londn" is closest to "londen", but that is itself merged, so it goes to "london".
    assert suggestions_for(("London", 9), ("Londen", 2), ("Londn", 1)) == {
        "londen": "london",
        "londn": "london",
    }


# ---------------------------------------------------------------------------- mapping


CITIES = column(("New York", 5), ("new york", 2), ("NYC", 2), ("New Yrok", 1), ("Accra", 3))


def test_mapping_applies_case_then_merges():
    mapping = standardize_mapping(CITIES, "upper", {"nyc": "new york"})
    assert mapping == {
        "New York": "NEW YORK",
        "new york": "NEW YORK",
        "NYC": "NEW YORK",
        "New Yrok": "NEW YROK",
        "Accra": "ACCRA",
    }


def test_merge_chains_are_followed():
    mapping = standardize_mapping(CITIES, "keep", {"new yrok": "nyc", "nyc": "new york"})
    assert mapping["New Yrok"] == "New York"


@pytest.mark.parametrize(
    "merge",
    [{"paris": "new york"}, {"nyc": "paris"}, {"nyc": "accra", "accra": "nyc"}],
    ids=["unknown source", "unknown target", "loop"],
)
def test_bad_merges_are_rejected(merge):
    with pytest.raises(MergeError):
        standardize_mapping(CITIES, "keep", merge)


def test_merge_into_itself_is_ignored():
    assert standardize_mapping(CITIES, "keep", {"accra": "accra"}).get("Accra") is None


# -------------------------------------------------------------------- detector + transform


def frame(series: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"city": series, "n": [str(i) for i in range(len(series))]})


def test_detector_offers_a_review_with_case_and_suggestions():
    (issue,) = detect_inconsistent(frame(CITIES))
    review = issue.review
    assert review.case == "title"
    by_key = {v.key: v for v in review.values}
    assert list(by_key) == ["new york", "accra", "nyc", "new yrok"]
    assert by_key["new york"].count == 7
    assert by_key["new york"].display == {
        "keep": "New York",
        "title": "New York",
        "upper": "NEW YORK",
        "lower": "new york",
    }
    assert by_key["new yrok"].suggestion == "new york"
    assert by_key["new yrok"].reason == "Similar spelling"
    assert by_key["nyc"].suggestion is None

    standardize = next(f for f in issue.fixes if f.id == "standardize")
    assert standardize.recommended
    assert standardize.step == {
        "op": "standardize_values",
        "column": "city",
        "case": "title",
        "merge": {"new yrok": "new york"},
    }
    assert issue.count == 3  # "new york" x2 and "New Yrok"


def test_a_typo_alone_is_an_issue():
    (issue,) = detect_inconsistent(frame(column(("London", 6), ("Londn", 1), ("Paris", 5))))
    assert issue.count == 1
    assert issue.detail == '"Londn" → "London"'


def test_names_get_no_review_or_typo_merges():
    names = column(*[(f"Person {i}", 1) for i in range(40)], ("person 1", 1), ("Jon Smith", 1))
    df = pd.DataFrame({"full_name": names.rename("full_name")})
    (issue,) = detect_inconsistent(df)
    assert issue.review is None
    assert issue.fixes[0].step["case"] == "keep" and issue.fixes[0].step["merge"] == {}
    assert issue.count == 1  # only the case variant


def test_columns_with_too_many_values_get_no_review():
    many = column(*[(f"Store {i:03}", 2) for i in range(120)], ("store 001", 1))
    df = pd.DataFrame({"store": many.rename("store")})
    (issue,) = detect_inconsistent(df)
    assert issue.review is None


def test_transform_applies_case_and_merges():
    step = StandardizeValues(column="city", case="title", merge={"nyc": "new york"})
    out = apply_steps(frame(CITIES), [step])
    assert out["city"].value_counts().to_dict() == {"New York": 9, "Accra": 3, "New Yrok": 1}


def test_transform_rejects_stale_merges_without_echoing_values():
    step = StandardizeValues(column="city", merge={"secret value": "new york"})
    with pytest.raises(TransformError) as err:
        apply_steps(frame(CITIES), [step])
    assert "secret value" not in str(err.value)


def test_merge_size_is_bounded():
    with pytest.raises(ValidationError):
        StandardizeValues(column="c", merge={str(i): "x" for i in range(MAX_MERGES + 1)})


def test_api_round_trip(client):
    csv = b"city,n\n" + b"".join(
        f"{c},{i}\n".encode() for i, c in enumerate(["New York"] * 5 + ["NYC", "nyc", "New Yrok"])
    )
    body = client.post("/analyze", files={"file": ("d.csv", csv, "text/csv")}).json()
    (issue,) = [i for i in body["issues"] if i["category"] == "inconsistent"]
    assert issue["review"]["case"] == "title"

    step = {**issue["fixes"][0]["step"], "merge": {"nyc": "new york", "new yrok": "new york"}}
    res = client.post(
        "/transform", files={"file": ("d.csv", csv, "text/csv")}, data={"steps": json.dumps([step])}
    )
    assert res.status_code == 200
    assert set(res.text.splitlines()[1:]) == {f"New York,{i}" for i in range(8)}


def test_equally_common_spellings_prefer_the_columns_usual_style():
    names = column(
        ("ada lovelace", 1), ("Ada Lovelace", 1), ("Grace Hopper", 1), ("Alan Turing", 1)
    )
    assert standardize_mapping(names, "keep") == {"ada lovelace": "Ada Lovelace"}
