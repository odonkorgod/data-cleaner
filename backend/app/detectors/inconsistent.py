"""Detect text written inconsistently: case, spacing, punctuation and typos.

For a categorical column with at most ``MAX_REVIEW_VALUES`` distinct values, the issue carries
a ``review``: every distinct value with its count, how it looks in each case style, and
suggested merges for near-duplicates. The default fix applies the column's most common case
style and the suggested merges; the user can change both before downloading.

Other text columns (names, free text, or too many values to review) are only cleaned of case
and spacing variants, each written in its most common spelling.
"""

import pandas as pd

from app.categories import (
    CASE_STYLES,
    MAX_REVIEW_VALUES,
    case_style,
    group_values,
    standardize_mapping,
    suggest_merges,
)
from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import quoted
from app.models import FixOption, Issue, ReviewValue, ValueReview
from app.values import column_kind, is_mostly_numeric


def _describe(series: pd.Series, mapping: dict[str, str]) -> str:
    """'"new york", "NYC " → "New York" and 2 more values', for the biggest change."""
    counts = series[series.isin(list(mapping))].value_counts()
    targets: dict[str, int] = {}
    for spelling, cells in counts.items():
        targets[mapping[spelling]] = targets.get(mapping[spelling], 0) + int(cells)
    biggest = max(targets, key=lambda t: targets[t])
    variants = [s for s in counts.index if mapping[s] == biggest]
    detail = f'{quoted(variants)} → "{biggest}"'
    if len(targets) > 1:
        more = len(targets) - 1
        detail += f" and {more} more value{'s' if more > 1 else ''}"
    return detail


def detect_inconsistent(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []

    for column in df.columns:
        series = df[column]
        # Stray text in number columns is a type mismatch, reported separately.
        if is_mostly_numeric(series):
            continue

        groups = group_values(series)
        # Only categories get a case style and merge suggestions: in names or free text a
        # "typo" is usually a different person or note.
        reviewable = column_kind(series) == "nominal" and len(groups) <= MAX_REVIEW_VALUES
        if reviewable:
            style = case_style(series)
            suggestions = suggest_merges(groups)
        else:
            style, suggestions = "keep", {}
        merge = {key: s.target for key, s in suggestions.items()}

        mapping = standardize_mapping(series, style, merge, groups)
        if not mapping:
            continue
        mask = series.isin(list(mapping))
        label = "Standardize values" if reviewable else "Use the most common spelling"

        review = None
        if reviewable:
            values = []
            for group in groups.values():
                suggestion = suggestions.get(group.key)
                values.append(
                    ReviewValue(
                        key=group.key,
                        count=group.count,
                        display={s: group.display(s) for s in CASE_STYLES},
                        suggestion=suggestion.target if suggestion else None,
                        reason=suggestion.reason if suggestion else None,
                    )
                )
            review = ValueReview(case=style, values=values)

        issues.append(
            Issue(
                id=f"inconsistent:{column}",
                type="inconsistent_values",
                category="inconsistent",
                title=f"Inconsistent values in '{column}'",
                columns=[str(column)],
                count=int(mask.sum()),
                detail=_describe(series, mapping),
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                review=review,
                fixes=[
                    FixOption(
                        id="standardize",
                        label=label,
                        step={
                            "op": "standardize_values",
                            "column": column,
                            "case": style,
                            "merge": merge,
                        },
                        recommended=True,
                    ),
                    FixOption(id="leave", label="Leave as is", step=None),
                ],
            )
        )

    return issues
