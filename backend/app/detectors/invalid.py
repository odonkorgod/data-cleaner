"""Detect numbers that break a validity rule: a negative age, a month of 13, 130%.

Rules are suggested from the column name or from the data (see rules.py); the user can edit
them, and add rules of their own in the UI. The recommended fix clears the cells, so they can
be filled like any other missing value rather than capped to an invented number.
"""

import math

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import worst_values
from app.models import FixOption, Issue, NumberSummary, ValidityRule
from app.rules import suggested_rule
from app.values import is_identifier, is_mostly_numeric, present_numbers, quantile_grid, to_numbers


def invalid_fixes(column: str, low: float | None, high: float | None) -> list[FixOption]:
    step = {"op": "fix_invalid", "column": column, "min": low, "max": high}
    return [
        FixOption(
            id="clear",
            label="Clear (leave empty)",
            step={**step, "action": "clear"},
            recommended=True,
        ),
        FixOption(
            id="drop_rows", label="Drop rows that have them", step={**step, "action": "drop_rows"}
        ),
        FixOption(id="leave", label="Leave as is", step=None),
    ]


def detect_invalid(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []

    for column in df.columns:
        series = df[column]
        rule = suggested_rule(series)
        if rule is None:
            continue
        numbers = to_numbers(series)
        mask = rule.violations(numbers)
        count = int(mask.sum())
        if count == 0:
            continue

        # Furthest outside the rule first.
        low = rule.min if rule.min is not None else -math.inf
        high = rule.max if rule.max is not None else math.inf
        badness = (low - numbers).clip(lower=0) + (numbers - high).clip(lower=0)

        issues.append(
            Issue(
                id=f"invalid:{column}",
                type="invalid_values",
                category="invalid",
                title=f"Invalid values in '{column}'",
                columns=[str(column)],
                count=count,
                detail=f"Found {worst_values(series, badness[mask])}",
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                rule=ValidityRule(
                    min=rule.min, max=rule.max, reason=rule.reason, source=rule.source
                ),
                fixes=invalid_fixes(column, rule.min, rule.max),
            )
        )

    return issues


def number_summaries(df: pd.DataFrame) -> dict[str, NumberSummary]:
    """Every number column the user could add a rule to (not IDs or codes)."""
    summaries: dict[str, NumberSummary] = {}
    for column in df.columns:
        series = df[column]
        if not is_mostly_numeric(series) or is_identifier(series):
            continue
        numbers = present_numbers(series)
        if not numbers.empty:
            summaries[str(column)] = NumberSummary(
                values=len(numbers), quantiles=quantile_grid(numbers)
            )
    return summaries
