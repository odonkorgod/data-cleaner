"""Detect numbers far outside a column's usual range (Tukey's fences, see values.py).

Detection always uses the usual range. To fix, the user can cap (winsorize) or drop at that
range, at percentiles, or at values of their own; ``cutoffs`` carries what the UI needs to
prefill those and preview how many rows each would affect.

Columns whose numbers label rather than measure (IDs, keys, codes, phone numbers) and ordinal
scales (ratings 1–10, 0/1 flags) are skipped: an "outlying" ID or a rating of 1 is not an error.
"""

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import MAX_EXAMPLES
from app.models import FixOption, Issue, OutlierCutoffs
from app.values import (
    column_kind,
    format_number,
    is_identifier,
    is_mostly_numeric,
    outlier_range,
    present_numbers,
    to_numbers,
)

# Numbers in the summary are shown with at most this many decimals. Display only: the fix
# itself always uses the exact values.
DISPLAY_DECIMALS = 2
# Suggested percentile cut-offs, and the fewest values for which percentiles mean anything
# (with fewer, the 1st percentile is just the smallest value).
DEFAULT_PERCENTILES = (1.0, 99.0)
MIN_VALUES_FOR_PERCENTILES = 100
# Quantiles sent to the UI for previews: every half percentile, 0 to 100.
QUANTILE_POINTS = [i / 200 for i in range(201)]


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
        if not is_mostly_numeric(series) or is_identifier(series):
            continue
        if column_kind(series) == "ordinal":
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

        # Most extreme first: furthest from the middle of the usual range.
        middle = (lower + upper) / 2
        extremes = (numbers[mask] - middle).abs().sort_values(ascending=False).index
        # Each value once: "found 150, 120", not "found 150, 120, 120".
        distinct = dict.fromkeys(_short(str(series[i])) for i in extremes)
        examples = ", ".join(list(distinct)[:MAX_EXAMPLES])

        present = present_numbers(series)
        cutoffs = OutlierCutoffs(
            lower=lower,
            upper=upper,
            # Exact, as written, to prefill the inputs; the detail line shows them shortened.
            lower_text=_written(series, numbers, lower),
            upper_text=_written(series, numbers, upper),
            values=len(present),
            quantiles=present.quantile(QUANTILE_POINTS, interpolation="nearest").tolist(),
            percentiles_ok=len(present) >= MIN_VALUES_FOR_PERCENTILES,
            lower_pct=DEFAULT_PERCENTILES[0],
            upper_pct=DEFAULT_PERCENTILES[1],
        )

        step = {"op": "fix_outliers", "column": column, "lower": lower, "upper": upper}
        issues.append(
            Issue(
                id=f"outliers:{column}",
                type="outliers",
                category="outliers",
                title=f"Outliers in '{column}'",
                columns=[str(column)],
                count=count,
                # The usual range itself is shown with the cut-offs.
                detail=f"Found {examples}",
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                cutoffs=cutoffs,
                fixes=[
                    FixOption(
                        id="cap",
                        label="Cap at the cut-offs (winsorize)",
                        step={**step, "action": "cap"},
                    ),
                    FixOption(
                        id="drop_rows",
                        label="Drop rows outside the cut-offs",
                        step={**step, "action": "drop_rows"},
                    ),
                    FixOption(id="leave", label="Leave as is", step=None),
                ],
            )
        )

    return issues
