"""Detect numbers far outside a column's usual range (Tukey's fences, see values.py)."""

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import MAX_EXAMPLES
from app.models import FixOption, Issue
from app.values import format_number, is_mostly_numeric, outlier_range, to_numbers

# Numbers in the summary are shown with at most this many decimals. Display only: the fix
# itself always uses the exact values.
DISPLAY_DECIMALS = 2


def _written(series: pd.Series, numbers: pd.Series, value: float) -> str:
    """How a value is written in the column ("1.50", not "1.5")."""
    matches = series[numbers == value]
    return str(matches.iloc[0]) if not matches.empty else format_number(value, series.dropna())


def _short(text: str) -> str:
    """Shorten long decimals for display ("1.23571" -> "1.24"); other text is unchanged."""
    whole, dot, decimals = text.partition(".")
    if dot and len(decimals) > DISPLAY_DECIMALS and decimals.isdigit():
        return f"{float(text):.{DISPLAY_DECIMALS}f}"
    return text


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

        low_text = _short(_written(series, numbers, lower))
        high_text = _short(_written(series, numbers, upper))
        # Most extreme first: furthest from the middle of the usual range.
        middle = (lower + upper) / 2
        extremes = (numbers[mask] - middle).abs().sort_values(ascending=False).index
        examples = ", ".join(_short(str(series[i])) for i in extremes[:MAX_EXAMPLES])

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
