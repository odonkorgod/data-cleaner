"""Detect numbers far outside a column's usual range (Tukey's fences, see values.py)."""

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import MAX_EXAMPLES
from app.models import FixOption, Issue
from app.values import is_mostly_numeric, outlier_range, to_numbers


def _written(series: pd.Series, numbers: pd.Series, value: float) -> str:
    """How a value is written in the column ("1.50", not "1.5")."""
    return str(series[numbers == value].iloc[0])


def detect_outliers(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []

    for column in df.columns:
        series = df[column]
        if not is_mostly_numeric(series):
            continue
        bounds = outlier_range(series)
        if bounds is None:
            continue
        lower, upper = bounds
        numbers = to_numbers(series)
        mask = (numbers < lower) | (numbers > upper)
        count = int(mask.sum())
        if count == 0:
            continue

        low_text, high_text = _written(series, numbers, lower), _written(series, numbers, upper)
        # Most extreme first: furthest from the middle of the usual range.
        middle = (lower + upper) / 2
        extremes = (numbers[mask] - middle).abs().sort_values(ascending=False).index
        examples = ", ".join(str(series[i]) for i in extremes[:MAX_EXAMPLES])

        step = {"op": "fix_outliers", "column": column, "lower": lower, "upper": upper}
        issues.append(
            Issue(
                id=f"outliers:{column}",
                type="outliers",
                category="outliers",
                title=f"Outliers in '{column}'",
                columns=[str(column)],
                count=count,
                detail=f"Usual range {low_text} to {high_text}, found {examples}",
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                fixes=[
                    FixOption(
                        id="cap",
                        label=f"Cap to the usual range ({low_text} to {high_text})",
                        step={**step, "action": "cap"},
                    ),
                    FixOption(
                        id="drop_rows",
                        label="Drop rows that have them",
                        step={**step, "action": "drop_rows"},
                    ),
                    FixOption(id="leave", label="Leave as is", step=None),
                ],
            )
        )

    return issues
