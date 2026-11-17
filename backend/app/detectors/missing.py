"""Detect columns that contain missing values, and recommend how to fill each one.

The recommendation follows the kind of data in the column (see ``column_kind`` in values.py):

* roughly normal numbers  -> mean (it is the typical value of a bell curve)
* other continuous numbers -> median (robust to skew and heavy tails)
* categories, including ordinal scales like 1–10 scores -> mode (the most common value)
* IDs and free text        -> leave as is (no single value would be right)

Placeholders like "N/A" or "NULL" count as missing (see placeholders.py). When a column has
them, the user can also make them truly empty cells.
"""

from dataclasses import dataclass

import pandas as pd

from app.config import DROP_COLUMN_MISSING_SHARE, SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import quoted
from app.models import FixOption, Issue, SparseColumn
from app.placeholders import placeholder_frame
from app.values import (
    MAX_NORMAL_SKEW,
    column_kind,
    distribution_shape,
    is_mostly_numeric,
    present_numbers,
)


@dataclass(frozen=True)
class FillAdvice:
    fix_id: str  # id of the recommended FixOption
    reason: str  # one line, shown to the user


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def recommend_fill(series: pd.Series) -> FillAdvice | None:
    """The recommended way to fill this column's missing values, with a short reason."""
    kind = column_kind(series)

    if kind == "empty":
        return None
    if kind == "unique":
        return FillAdvice(
            "leave",
            "Values rarely repeat (like IDs or free text), so no single value fits. "
            "Leave blank, or fill with your own placeholder.",
        )
    if kind == "nominal":
        distinct = series.nunique()
        return FillAdvice(
            "fill_mode",
            f"Categorical ({distinct} distinct values), so the mode (most common value) fits best.",
        )
    if kind == "ordinal":
        numbers = present_numbers(series)
        low, high = _number(numbers.min()), _number(numbers.max())
        if numbers.nunique() == 2:
            return FillAdvice(
                "fill_mode",
                f"Only two values ({low} and {high}), treated as categories, "
                "so the mode (most common value) fits best.",
            )
        return FillAdvice(
            "fill_mode",
            f"Whole numbers on a {low}–{high} scale, treated as ordinal categories, "
            "so the mode (most common value) fits best.",
        )

    # Continuous: choose between mean and median by the shape of the distribution.
    numbers = present_numbers(series)
    shape = distribution_shape(numbers)
    if shape is None:
        return FillAdvice(
            "fill_median",
            f"Too few numbers ({len(numbers)}) to judge the distribution, "
            "so the median is the safer choice.",
        )
    if shape.roughly_normal:
        return FillAdvice(
            "fill_mean",
            f"Roughly normal (skewness {shape.skewness:.1f}), so the mean is the typical value.",
        )
    if abs(shape.skewness) > MAX_NORMAL_SKEW:
        direction = "right" if shape.skewness > 0 else "left"
        why = f"Skewed to the {direction} (skewness {shape.skewness:.1f})"
    else:
        why = f"Not bell-shaped (kurtosis {shape.kurtosis:.1f})"
    return FillAdvice("fill_median", f"{why}, so the median is more typical than the mean.")


def detect_missing(df: pd.DataFrame, found: pd.DataFrame | None = None) -> list[Issue]:
    """``found`` is ``placeholder_frame(df)``, if the caller already has it."""
    if found is None:
        found = placeholder_frame(df)
    issues: list[Issue] = []

    for column in df.columns:
        placeholders = found[column]
        series = df[column].mask(placeholders)  # placeholders become empty cells
        mask = series.isna()
        count = int(mask.sum())
        if count == 0:
            continue

        fixes = [
            FixOption(
                id="drop_rows",
                label="Drop rows with a missing value",
                step={"op": "drop_null_rows", "column": column},
            ),
        ]
        # Mean and median use the column's numbers, ignoring any stray text.
        if is_mostly_numeric(series):
            for strategy in ("mean", "median"):
                fixes.append(
                    FixOption(
                        id=f"fill_{strategy}",
                        label=f"Fill with the {strategy}",
                        step={"op": "fill_nulls", "column": column, "strategy": strategy},
                    )
                )
        fixes.append(
            FixOption(
                id="fill_mode",
                label="Fill with the mode",
                step={"op": "fill_nulls", "column": column, "strategy": "mode"},
            )
        )
        fixes.append(
            FixOption(
                id="fill_constant",
                label="Fill with a value I choose",
                step={"op": "fill_nulls", "column": column, "strategy": "constant"},
                needs_value=True,
            )
        )
        if placeholders.any():
            fixes.append(
                FixOption(
                    id="clear_placeholders",
                    label="Make placeholders empty",
                    step={"op": "clear_placeholders", "column": column},
                )
            )
        fixes.append(FixOption(id="leave", label="Leave as is", step=None))

        advice = recommend_fill(series)
        recommended = advice.fix_id if advice else None
        if placeholders.any() and recommended in (None, "leave"):
            # No value fits, but empty cells are still cleaner than "N/A" text.
            recommended = "clear_placeholders"
        for fix in fixes:
            fix.recommended = fix.id == recommended

        details = []
        if placeholders.any():
            spellings = df[column][placeholders].value_counts().index  # most common first
            details.append(f"Counts {quoted(spellings)} as missing.")
        if advice is not None:
            details.append(advice.reason)

        issues.append(
            Issue(
                id=f"missing:{column}",
                type="missing_values",
                category="missingness",
                title=f"Missing values in '{column}'",
                columns=[str(column)],
                count=count,
                detail=" ".join(details) or None,
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                fixes=fixes,
            )
        )

    return issues


def sparse_columns(blanked: pd.DataFrame, unnamed: set[str]) -> list[SparseColumn]:
    """Columns with at least ``DROP_COLUMN_MISSING_SHARE`` of their cells empty.

    Named columns come first, then unnamed ones (often blank columns from trailing commas),
    each least empty first: the ones most likely to hold data worth keeping lead the list.

    ``blanked`` has placeholders already turned into empty cells. Returns nothing if every
    column qualifies: removing them all would leave no file.
    """
    rows = len(blanked)
    if rows == 0:
        return []
    missing = blanked.isna().sum()
    found = [
        SparseColumn(column=str(c), missing=int(n), unnamed=str(c) in unnamed)
        for c, n in missing.items()
        if n / rows >= DROP_COLUMN_MISSING_SHARE
    ]
    if len(found) == len(blanked.columns):
        return []
    return sorted(found, key=lambda c: (c.unnamed, c.missing))  # stable: ties keep file order
