"""Helpers for reasoning about cell values, shared by detectors and transforms.

Every cell is text (see csv_io.py). These helpers decide when text is a number, which numbers
are outliers, and which spellings are variants of the same value. Detectors and transforms
both call them, so what the user is shown and what a fix does always agree.
"""

import pandas as pd

# A column counts as "mostly numeric" when at least this share of its values are numbers.
# Below that it is a text column that happens to contain some numbers.
MOSTLY_NUMERIC = 0.8
# Fewer values than this and quartiles are too noisy to call anything an outlier.
MIN_VALUES_FOR_OUTLIERS = 8
# Tukey's rule: values beyond 1.5 interquartile ranges from the quartiles are outliers.
IQR_FACTOR = 1.5


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
