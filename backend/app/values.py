"""Helpers for reasoning about cell values, shared by detectors and transforms.

Every cell is text (see csv_io.py). These helpers decide when text is a number, which numbers
are outliers, and which spellings are variants of the same value. Detectors and transforms
both call them, so what the user is shown and what a fix does always agree.
"""

import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd

# A column counts as "mostly numeric" when at least this share of its values are numbers.
# Below that it is a text column that happens to contain some numbers.
MOSTLY_NUMERIC = 0.8
# Fewer values than this and quartiles are too noisy to call anything an outlier.
MIN_VALUES_FOR_OUTLIERS = 8
# Tukey's rule: values beyond 1.5 interquartile ranges from the quartiles are outliers.
IQR_FACTOR = 1.5

# --- Column kinds (see column_kind) ---
# Categories repeat: at most this share of a column's values may be distinct.
MAX_DISTINCT_SHARE = 0.5
# Whole numbers spanning at most this many steps (1–10, 0–10, 1–5) form an ordinal scale.
# Values are compared as numbers, so "7", "7.0" and "7.00" are all the whole number 7.
MAX_ORDINAL_SPAN = 10
# Whole numbers that are all different, over at least this many rows, may be IDs...
MIN_VALUES_FOR_ID = 20
# ...if they are close to a sequence (1001, 1002, 1005, ...) or the column is named like one.
MAX_ID_GAP = 2.0  # (max - min + 1) / count
# Only consulted for columns of unique whole numbers. Matches "id", "customer_id", "Customer ID",
# "id_number", "account_number", "invoice_no", "key" in any case, and "customerId"/"orderID" only
# in camelCase, so ordinary words ending in "id" ("paid", "valid") don't match.
ID_NAME = re.compile(
    r"(?i:^id$|^id[_\s-]|[_\s-](id|number|no|num|code)$|^(key|uuid|guid|code)$)"
    r"|[a-z](Id|ID|Number|No|Num|Code)$"
)

# --- Distribution shape (see distribution_shape) ---
# Fewer numbers than this and skewness/kurtosis are too noisy to judge the shape.
MIN_VALUES_FOR_SHAPE = 20
# Rules of thumb for "roughly normal": nearly symmetric, and tails like a bell curve's.
# The thresholds are fixed rather than widened for small samples on purpose: wrongly
# recommending the median for normal data costs little (the two are close), while wrongly
# recommending the mean for skewed data is the mistake worth avoiding. In simulation, normal
# data passes 72% of the time at 30 values and 92%+ from 100; lognormal/exponential data
# passes under 10% from 30 values and never from 100.
MAX_NORMAL_SKEW = 0.5
MAX_NORMAL_KURTOSIS = 1.0  # excess kurtosis: 0 for a normal distribution


def to_numbers(series: pd.Series) -> pd.Series:
    """Every cell as a float, NaN where the cell is empty or not a number. Same index."""
    return pd.to_numeric(series, errors="coerce").astype(float)


def numeric_values(series: pd.Series) -> pd.Series | None:
    """The column's non-missing values as numbers, or None if any of them is not a number."""
    present = series.dropna()
    if present.empty:
        return None
    numbers = to_numbers(present)
    if numbers.isna().any():
        return None
    return numbers


def numeric_share(series: pd.Series) -> float:
    """Share of non-missing values that are numbers (0 for an empty column)."""
    present = series.dropna()
    if present.empty:
        return 0.0
    return float(to_numbers(present).notna().mean())


def is_mostly_numeric(series: pd.Series) -> bool:
    return numeric_share(series) >= MOSTLY_NUMERIC


def non_numeric_mask(series: pd.Series) -> pd.Series:
    """True for cells that hold something other than a number (empty cells are False)."""
    return series.notna() & to_numbers(series).isna()


def _looks_like_ids(numbers: pd.Series, name: object) -> bool:
    """Unique whole numbers that are near-sequential, or in a column named like an ID.

    Uniqueness alone is not enough: incomes or prices can all differ without being IDs.
    """
    if len(numbers) < MIN_VALUES_FOR_ID or numbers.nunique() != len(numbers):
        return False
    sequential = (numbers.max() - numbers.min() + 1) / len(numbers) <= MAX_ID_GAP
    return sequential or bool(ID_NAME.search(str(name)))


def present_numbers(series: pd.Series) -> pd.Series:
    """The column's values that are numbers, ignoring empty cells and stray text."""
    return to_numbers(series).dropna()


ColumnKind = Literal["empty", "continuous", "ordinal", "nominal", "unique"]


def column_kind(series: pd.Series) -> ColumnKind:
    """What sort of data a column holds, judged from its non-empty values.

    * ``ordinal``: whole numbers on a short, repeating scale, e.g. satisfaction scores 1–10.
    * ``continuous``: any other numbers (ages, prices, measurements).
    * ``nominal``: text categories that repeat, e.g. city or plan tier.
    * ``unique``: values that (almost) never repeat: IDs, names, free-text notes.
    * ``empty``: no values at all.

    Mostly-numeric columns are judged by their numbers, ignoring stray text.
    """
    present = series.dropna()
    if present.empty:
        return "empty"

    if is_mostly_numeric(series):
        numbers = present_numbers(series)  # "3.0000" -> 3.0, so zero decimals still count
        distinct = numbers.nunique()
        whole = bool((numbers % 1 == 0).all())
        repeats = distinct <= MAX_DISTINCT_SHARE * len(numbers)
        if whole and repeats and numbers.max() - numbers.min() <= MAX_ORDINAL_SPAN:
            return "ordinal"
        if whole and _looks_like_ids(numbers, series.name):
            return "unique"
        return "continuous"

    repeats = present.nunique() <= MAX_DISTINCT_SHARE * len(present)
    return "nominal" if repeats else "unique"


def mode_value(series: pd.Series) -> str | None:
    """The column's most common value, written the way the column writes it.

    In number columns values are compared as numbers, so "7", "7.0" and "7.00" count as one
    value; the result is that number's most common spelling. Ties between values go to the
    smallest (as pandas' mode does), ties between spellings to the one seen first.
    """
    present = series.dropna()
    if present.empty:
        return None
    if not is_mostly_numeric(series):
        return str(present.mode().iloc[0])

    numbers = to_numbers(present)  # stray text becomes NaN and is ignored
    modal = numbers.mode(dropna=True).iloc[0]
    spellings = present[numbers == modal]
    counts = spellings.value_counts()
    return max(spellings.drop_duplicates(), key=lambda s: counts[s])


def is_categorical(series: pd.Series) -> bool:
    """True for categories, whether text (nominal) or an ordered numeric scale (ordinal)."""
    return column_kind(series) in ("nominal", "ordinal")


@dataclass(frozen=True)
class Shape:
    skewness: float
    kurtosis: float  # excess kurtosis: 0 for a normal distribution

    @property
    def roughly_normal(self) -> bool:
        return abs(self.skewness) <= MAX_NORMAL_SKEW and abs(self.kurtosis) <= MAX_NORMAL_KURTOSIS


def distribution_shape(numbers: pd.Series) -> Shape | None:
    """Skewness and kurtosis of some numbers, or None if there are too few to judge.

    This deliberately measures *how far* from normal the data is rather than running a
    significance test: on large files a test like Shapiro-Wilk rejects normality over
    differences too small to matter, and for choosing mean vs median the size is what counts.
    """
    if len(numbers) < MIN_VALUES_FOR_SHAPE or numbers.nunique() < 2:
        return None
    return Shape(skewness=float(numbers.skew()), kurtosis=float(numbers.kurt()))


def format_number(value: float, present: pd.Series) -> str:
    """Write a computed number in the column's existing style.

    A whole number is written without a decimal point ("40") unless the column already uses
    decimals or exponents ("40.0"), so integer columns stay integer columns.
    """
    if value.is_integer() and not present.astype(str).str.contains(r"[.eE]").any():
        return str(int(value))
    return repr(value)


def outlier_range(series: pd.Series) -> tuple[float, float] | None:
    """The usual range of a numeric column: the lowest and highest values that are not outliers.

    Uses Tukey's fences, then snaps to the most extreme real values inside them (the box-plot
    whiskers), so capping replaces an outlier with a value that already exists in the data.
    Returns None when there are too few numbers or no spread to judge by.
    """
    numbers = to_numbers(series).dropna()
    if len(numbers) < MIN_VALUES_FOR_OUTLIERS:
        return None
    q1, q3 = numbers.quantile(0.25), numbers.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    inside = numbers[numbers.between(q1 - IQR_FACTOR * iqr, q3 + IQR_FACTOR * iqr)]
    # Exact, not rounded: the bounds must equal real values, or the edge values themselves would
    # be flagged and capped. Rounding for display happens in the outliers detector.
    return float(inside.min()), float(inside.max())


def normalize_text(value: str) -> str:
    """The comparison key for spelling variants: trimmed, single-spaced, case-insensitive."""
    return " ".join(value.split()).casefold()


def canonical_spellings(series: pd.Series) -> dict[str, str]:
    """Map every variant spelling to the canonical one for its group.

    Values that differ only in case or whitespace form a group. The canonical spelling is the
    most common one, ties going to the one that appears first. Values already in canonical
    form, and values with no variants, are left out of the mapping.
    """
    present = series.dropna()
    counts = present.value_counts()
    groups: dict[str, list[str]] = {}
    for value in present.drop_duplicates():  # order of first appearance
        groups.setdefault(normalize_text(value), []).append(value)

    mapping: dict[str, str] = {}
    for spellings in groups.values():
        if len(spellings) < 2:
            continue
        canonical = max(spellings, key=lambda s: counts[s])  # max() keeps the first on ties
        for spelling in spellings:
            if spelling != canonical:
                mapping[spelling] = canonical
    return mapping
