"""Apply user-chosen fix steps to a DataFrame.

Steps run in the fixed order defined by ``STEP_ORDER`` in models.py, not the order they arrive.
"""

import pandas as pd

from app.models import (
    STEP_ORDER,
    DropDuplicates,
    DropNullRows,
    FillNulls,
    FixOutliers,
    FixStep,
    FixTypeMismatch,
    StandardizeValues,
)
from app.values import (
    canonical_spellings,
    format_number,
    is_mostly_numeric,
    mode_value,
    non_numeric_mask,
    numeric_values,
    present_numbers,
    to_numbers,
)


class TransformError(ValueError):
    """A step could not be applied. Messages name columns/strategies, never cell values."""


def _require_column(df: pd.DataFrame, column: str) -> None:
    if column not in df.columns:
        raise TransformError(f"Column '{column}' does not exist in this file.")


def _standardize_values(df: pd.DataFrame, step: StandardizeValues) -> pd.DataFrame:
    _require_column(df, step.column)
    mapping = canonical_spellings(df[step.column])
    if not mapping:
        return df
    out = df.copy()
    out[step.column] = df[step.column].replace(mapping)
    return out


def _fix_type_mismatch(df: pd.DataFrame, step: FixTypeMismatch) -> pd.DataFrame:
    _require_column(df, step.column)
    mask = non_numeric_mask(df[step.column])
    if step.action == "drop_rows":
        return df[~mask]
    out = df.copy()
    out.loc[mask, step.column] = None
    return out


def _as_text(bound: float, series: pd.Series, numbers: pd.Series) -> str:
    """The bound as it is written in the column (e.g. "1.50"), so capped cells match it."""
    matches = series[numbers == bound]
    return matches.iloc[0] if not matches.empty else format_number(bound, series.dropna())


def _fix_outliers(df: pd.DataFrame, step: FixOutliers) -> pd.DataFrame:
    _require_column(df, step.column)
    series = df[step.column]
    numbers = to_numbers(series)  # NaN for empty and non-numeric cells, which are left alone
    low, high = numbers < step.lower, numbers > step.upper

    if step.action == "drop_rows":
        return df[~(low | high)]
    out = df.copy()
    out.loc[low, step.column] = _as_text(step.lower, series, numbers)
    out.loc[high, step.column] = _as_text(step.upper, series, numbers)
    return out


def _fill_nulls(df: pd.DataFrame, step: FillNulls) -> pd.DataFrame:
    _require_column(df, step.column)
    series = df[step.column]
    numbers = numeric_values(series)

    if step.strategy in ("mean", "median"):
        # Stray text in a mostly numeric column is ignored, so it doesn't block the fill.
        if not is_mostly_numeric(series):
            raise TransformError(
                f"Cannot compute the {step.strategy} of non-numeric '{step.column}'."
            )
        found = present_numbers(series)
        value = found.mean() if step.strategy == "mean" else found.median()
        fill = format_number(round(float(value), 2), series.dropna())
    elif step.strategy == "mode":
        # Number columns compare as numbers, so "7", "7.0" and "7.00" count as one value.
        mode = mode_value(series)
        if mode is None:
            raise TransformError(f"Column '{step.column}' has no values to take a mode from.")
        fill = mode
    else:  # constant
        if step.value is None:
            raise TransformError(f"A value is required to fill '{step.column}'.")
        if numbers is not None and pd.isna(pd.to_numeric(step.value, errors="coerce")):
            raise TransformError(
                f"'{step.column}' is numeric, so the fill value must be a number."
            )
        # Written exactly as typed, so "0" stays "0" and "007" stays "007".
        fill = step.value

    out = df.copy()
    out[step.column] = series.fillna(fill)
    return out


def _drop_null_rows(df: pd.DataFrame, step: DropNullRows) -> pd.DataFrame:
    _require_column(df, step.column)
    return df.dropna(subset=[step.column])


def _drop_duplicates(df: pd.DataFrame, step: DropDuplicates) -> pd.DataFrame:
    return df.drop_duplicates(keep=step.keep)


def apply_steps(df: pd.DataFrame, steps: list[FixStep]) -> pd.DataFrame:
    # sorted() is stable, so steps with the same rank keep the order they were sent in.
    ordered = sorted(steps, key=lambda s: STEP_ORDER[s.op])

    result = df
    for step in ordered:
        if isinstance(step, StandardizeValues):
            result = _standardize_values(result, step)
        elif isinstance(step, FixTypeMismatch):
            result = _fix_type_mismatch(result, step)
        elif isinstance(step, FixOutliers):
            result = _fix_outliers(result, step)
        elif isinstance(step, FillNulls):
            result = _fill_nulls(result, step)
        elif isinstance(step, DropNullRows):
            result = _drop_null_rows(result, step)
        elif isinstance(step, DropDuplicates):
            result = _drop_duplicates(result, step)
    return result.reset_index(drop=True)
