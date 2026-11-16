"""Validity rules: the range a number column's values must fall in.

Unlike outliers (unusual but possible), a value outside its rule is impossible or not allowed:
a negative age, a month of 13, 130%. Rules come from three places:

* the column's name ("age" -> 0 to 120), see ``NAME_RULES``;
* the data: a column that is almost never negative probably has sign errors, see ``sign_rule``;
* the user, who can add a rule for any number column (e.g. "customers are 18+").

Name rules are suggestions, shown with their reason and editable. Guards keep them from firing
on names that only look similar: "age_days" is a duration, not an age; "price_change" can be
negative even though prices can't.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from app.values import is_identifier, is_mostly_numeric, present_numbers

# Fewer numbers than this and a rare negative could just as well be real.
MIN_VALUES_FOR_SIGN_RULE = 20
# At most this share negative, and the negatives look like sign errors rather than data.
MAX_NEGATIVE_SHARE = 0.01
# A percentage column with at least this share of values within 0–1 is on a 0–1 scale.
SHARE_SCALE = 0.9


@dataclass(frozen=True)
class Rule:
    min: float | None
    max: float | None
    reason: str  # shown to the user
    source: Literal["name", "data"]

    def violations(self, numbers: pd.Series) -> pd.Series:
        """True where a number breaks the rule (empty and non-numeric cells are False)."""
        bad = pd.Series(False, index=numbers.index)
        if self.min is not None:
            bad |= numbers < self.min
        if self.max is not None:
            bad |= numbers > self.max
        return bad


# ------------------------------------------------------------------------- name rules


def name_words(name: object) -> list[str]:
    """The words of a column name, lowercased.

    "customerAge" -> ["customer", "age"]; "orderID" -> ["order", "id"];
    "age_in_days" -> ["age", "in", "days"].
    """
    return [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", str(name))]


# Words that turn a quantity into a time span or a change, which the rules don't describe:
# "age_days" isn't an age in years, "price_change" can be negative.
DURATION_WORDS = {"days", "weeks", "months", "hours", "minutes", "seconds", "mins", "hrs", "ms"}
CHANGE_WORDS = {
    "change", "diff", "difference", "delta", "growth", "variance", "profit", "loss",
    "balance", "return", "returns", "adjustment", "margin", "offset", "pnl",
}
# Quantities that can't be negative.
NON_NEGATIVE_WORDS = {
    "price", "cost", "fee", "fees", "quantity", "qty", "count", "units", "salary", "wage",
    "wages", "weight", "height", "length", "width", "depth", "distance", "duration",
    "population", "area", "volume",
}


def _percent_rule(numbers: pd.Series) -> Rule:
    if numbers.between(0, 1).mean() >= SHARE_SCALE:
        return Rule(0, 1, "Shares are between 0 and 1.", "name")
    return Rule(0, 100, "Percentages are between 0 and 100.", "name")


# (matches the column's words, rule for its numbers). The first match wins.
NAME_RULES: list[tuple[Callable[[set[str]], bool], Callable[[pd.Series], Rule]]] = [
    (
        lambda w: "age" in w and not w & DURATION_WORDS,
        lambda _: Rule(0, 120, "Ages are between 0 and 120.", "name"),
    ),
    (
        lambda w: bool(w & {"percent", "percentage", "pct"}) and not w & CHANGE_WORDS,
        _percent_rule,
    ),
    (
        lambda w: "month" in w,
        lambda _: Rule(1, 12, "Months are numbered 1 to 12.", "name"),
    ),
    (
        lambda w: "day" in w and not w & {"week", "weekday", "year"},
        lambda _: Rule(1, 31, "Days of the month are 1 to 31.", "name"),
    ),
    (
        lambda w: "hour" in w,
        lambda _: Rule(0, 23, "Hours of the day are 0 to 23.", "name"),
    ),
    (
        lambda w: "minute" in w,
        lambda _: Rule(0, 59, "Minutes are 0 to 59.", "name"),
    ),
    (
        lambda w: bool(w & {"lat", "latitude"}),
        lambda _: Rule(-90, 90, "Latitudes are between -90 and 90.", "name"),
    ),
    (
        lambda w: bool(w & {"lon", "lng", "longitude"}),
        lambda _: Rule(-180, 180, "Longitudes are between -180 and 180.", "name"),
    ),
    (
        lambda w: bool(w & {"year", "yr"}),
        lambda _: Rule(1900, date.today().year + 1, "Years should be recent, not future.", "name"),
    ),
    (
        lambda w: bool(w & NON_NEGATIVE_WORDS) and not w & CHANGE_WORDS,
        lambda _: Rule(0, None, "This kind of quantity can't be negative.", "name"),
    ),
]


def name_rule(name: object, numbers: pd.Series) -> Rule | None:
    words = set(name_words(name))
    for matches, make in NAME_RULES:
        if matches(words):
            return make(numbers)
    return None


# ------------------------------------------------------------------------- data rules


def sign_rule(numbers: pd.Series) -> Rule | None:
    """Suggest "0 or more" when a handful of values are negative among many that aren't."""
    if len(numbers) < MIN_VALUES_FOR_SIGN_RULE:
        return None
    negative = int((numbers < 0).sum())
    if negative == 0 or negative > MAX_NEGATIVE_SHARE * len(numbers):
        return None
    reason = f"Only {negative:,} of {len(numbers):,} values are negative: likely sign errors."
    return Rule(0, None, reason, "data")


def suggested_rule(series: pd.Series) -> Rule | None:
    """The rule we'd suggest for a column, or None (text, IDs and codes get none)."""
    if not is_mostly_numeric(series) or is_identifier(series):
        return None
    numbers = present_numbers(series)
    if numbers.empty:
        return None
    return name_rule(series.name, numbers) or sign_rule(numbers)
