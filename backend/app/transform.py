"""Apply user-chosen fix steps to a DataFrame.

Steps run in the fixed order defined by ``STEP_ORDER`` in models.py, not the order they arrive.
They see placeholders like "N/A" as empty cells (see placeholders.py).
"""

import pandas as pd

from app.categories import MergeError, standardize_mapping
from app.models import (
    STEP_ORDER,
    ClearPlaceholders,
    DropColumns,
    DropDuplicates,
    DropNullRows,
    FillNulls,
    FixInvalid,
    FixOutliers,
    FixStep,
    FixTypeMismatch,
    StandardizeValues,
)
from app.placeholders import placeholder_frame
from app.rules import suggested_rule
from app.values import (
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


def _drop_columns(df: pd.DataFrame, step: DropColumns) -> pd.DataFrame:
    for column in step.columns:
        _require_column(df, column)
    if set(df.columns) <= set(step.columns):
        raise TransformError("Can't remove every column.")
    return df.drop(columns=step.columns)


def _standardize_values(df: pd.DataFrame, step: StandardizeValues) -> pd.DataFrame:
    _require_column(df, step.column)
    try:
        mapping = standardize_mapping(df[step.column], step.case, step.merge, rename=step.rename)
    except MergeError:
        raise TransformError(
            f"The values reviewed for '{step.column}' don't match the file. Analyze it again."
        ) from None
    if not mapping:
        return df
    out = df.copy()
    # One lookup per cell, so a rewritten value is never rewritten again.
    out[step.column] = df[step.column].map(lambda v: mapping.get(v, v), na_action="ignore")
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


def _fix_invalid(df: pd.DataFrame, step: FixInvalid) -> pd.DataFrame:
    _require_column(df, step.column)
    numbers = to_numbers(df[step.column])  # empty and non-numeric cells are left alone
    bad = pd.Series(False, index=df.index)
    if step.min is not None:
        bad |= numbers < step.min
    if step.max is not None:
        bad |= numbers > step.max
    if step.action == "drop_rows":
        return df[~bad]
    out = df.copy()
    out.loc[bad, step.column] = None
    return out


def _percentile(numbers: pd.Series, pct: float | None) -> float | None:
    """The real data value at a percentile, so capped cells hold values the column already has."""
    if pct is None or numbers.empty:
        return None
    return float(numbers.quantile(pct / 100, interpolation="nearest"))


def _resolve_percentiles(df: pd.DataFrame, step: FixOutliers) -> FixOutliers:
    """Turn percentile cut-offs into values, from the column as uploaded.

    Done before any step runs, so "the 99th percentile" means the same thing as in the preview,
    whatever rows other fixes drop first.
    """
    if step.lower_pct is None and step.upper_pct is None:
        return step
    _require_column(df, step.column)
    numbers = to_numbers(df[step.column])
    # Like outlier detection, leave out values that break the column's suggested rule.
    rule = suggested_rule(df[step.column])
    present = (numbers[~rule.violations(numbers)] if rule else numbers).dropna()
    return step.model_copy(
        update={
            "lower": _percentile(present, step.lower_pct),
            "upper": _percentile(present, step.upper_pct),
            "lower_pct": None,
            "upper_pct": None,
        }
    )


def _fix_outliers(df: pd.DataFrame, step: FixOutliers) -> pd.DataFrame:
    _require_column(df, step.column)
    series = df[step.column]
    numbers = to_numbers(series)  # NaN for empty and non-numeric cells, which are left alone
    lower, upper = step.lower, step.upper  # percentiles were resolved in apply_steps

    # A missing bound means no limit on that side.
    low = numbers < lower if lower is not None else pd.Series(False, index=numbers.index)
    high = numbers > upper if upper is not None else pd.Series(False, index=numbers.index)

    if step.action == "drop_rows":
        return df[~(low | high)]
    out = df.copy()
    if lower is not None:
        out.loc[low, step.column] = _as_text(lower, series, numbers)
    if upper is not None:
        out.loc[high, step.column] = _as_text(upper, series, numbers)
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


def _restore_placeholders(
    result: pd.DataFrame, original: pd.DataFrame, placeholders: pd.DataFrame, cleared: set[str]
) -> pd.DataFrame:
    """Write back, as uploaded, placeholders that are still missing and weren't cleared."""
    out = result
    for column in result.columns:
        if column in cleared:
            continue
        restore = placeholders.loc[result.index, column] & result[column].isna()
        if restore.any():
            if out is result:
                out = result.copy()
            rows = restore[restore].index
            out.loc[rows, column] = original.loc[rows, column]
    return out


def apply_steps(df: pd.DataFrame, steps: list[FixStep]) -> pd.DataFrame:
    # Every step treats placeholders ("N/A", "NULL") as the empty cells they stand for.
    placeholders = placeholder_frame(df)
    blanked = df.mask(placeholders)

    steps = [_resolve_percentiles(blanked, s) if isinstance(s, FixOutliers) else s for s in steps]
    # sorted() is stable, so steps with the same rank keep the order they were sent in.
    ordered = sorted(steps, key=lambda s: STEP_ORDER[s.op])

    cleared: set[str] = set()
    result = blanked
    for step in ordered:
        if isinstance(step, DropColumns):
            result = _drop_columns(result, step)
        elif isinstance(step, StandardizeValues):
            result = _standardize_values(result, step)
        elif isinstance(step, FixTypeMismatch):
            result = _fix_type_mismatch(result, step)
        elif isinstance(step, FixInvalid):
            result = _fix_invalid(result, step)
        elif isinstance(step, FixOutliers):
            result = _fix_outliers(result, step)
        elif isinstance(step, FillNulls):
            result = _fill_nulls(result, step)
        elif isinstance(step, ClearPlaceholders):
            _require_column(result, step.column)
            cleared.add(step.column)  # they are already empty; just don't restore them
        elif isinstance(step, DropNullRows):
            result = _drop_null_rows(result, step)
        elif isinstance(step, DropDuplicates):
            result = _drop_duplicates(result, step)

    result = _restore_placeholders(result, df, placeholders, cleared)
    return result.reset_index(drop=True)
