"""Apply user-chosen fix steps to a DataFrame.

Steps run in the fixed order defined by ``STEP_ORDER`` in models.py, not the order they arrive.
"""

import pandas as pd

from app.csv_io import numeric_values
from app.models import STEP_ORDER, DropDuplicates, DropNullRows, FillNulls, FixStep


class TransformError(ValueError):
    """A step could not be applied. Messages name columns/strategies, never cell values."""


def _require_column(df: pd.DataFrame, column: str) -> None:
    if column not in df.columns:
        raise TransformError(f"Column '{column}' does not exist in this file.")


def _format_number(value: float, present: pd.Series) -> str:
    """Write a computed fill value in the column's existing style.

    A whole number is written without a decimal point ("40") unless the column already uses
    decimals or exponents ("40.0"), so integer columns stay integer columns.
    """
    if value.is_integer() and not present.str.contains(r"[.eE]").any():
        return str(int(value))
    return repr(value)


def _fill_nulls(df: pd.DataFrame, step: FillNulls) -> pd.DataFrame:
    _require_column(df, step.column)
    series = df[step.column]
    numbers = numeric_values(series)

    if step.strategy in ("mean", "median"):
        if numbers is None:
            raise TransformError(
                f"Cannot compute the {step.strategy} of non-numeric '{step.column}'."
            )
        value = numbers.mean() if step.strategy == "mean" else numbers.median()
        fill = _format_number(float(value), series.dropna())
    elif step.strategy == "mode":
        modes = series.mode(dropna=True)
        if modes.empty:
            raise TransformError(f"Column '{step.column}' has no values to take a mode from.")
        fill = modes.iloc[0]
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
        if isinstance(step, FillNulls):
            result = _fill_nulls(result, step)
        elif isinstance(step, DropNullRows):
            result = _drop_null_rows(result, step)
        elif isinstance(step, DropDuplicates):
            result = _drop_duplicates(result, step)
    return result.reset_index(drop=True)
