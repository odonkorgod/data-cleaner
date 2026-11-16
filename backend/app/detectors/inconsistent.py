"""Detect the same value written differently ("New York", "new york", " New York")."""

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import quoted
from app.models import FixOption, Issue
from app.values import canonical_spellings, is_mostly_numeric


def detect_inconsistent(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []

    for column in df.columns:
        series = df[column]
        # Stray text in number columns is a type mismatch, reported separately.
        if is_mostly_numeric(series):
            continue
        mapping = canonical_spellings(series)
        if not mapping:
            continue

        mask = series.isin(list(mapping))
        count = int(mask.sum())

        # Describe the group with the most cells to rewrite.
        counts = series[mask].value_counts()
        groups: dict[str, int] = {}
        for variant, canonical in mapping.items():
            groups[canonical] = groups.get(canonical, 0) + int(counts[variant])
        biggest = max(groups, key=lambda c: groups[c])
        variants = [v for v in counts.index if mapping[v] == biggest]
        detail = f"{quoted(variants)} → \"{biggest}\""
        if len(groups) > 1:
            more = len(groups) - 1
            detail += f" and {more} more value{'s' if more > 1 else ''}"

        issues.append(
            Issue(
                id=f"inconsistent:{column}",
                type="inconsistent_values",
                category="inconsistent",
                title=f"Inconsistent spellings in '{column}'",
                columns=[str(column)],
                count=count,
                detail=detail,
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                fixes=[
                    FixOption(
                        id="standardize",
                        label="Use the most common spelling",
                        step={"op": "standardize_values", "column": column},
                    ),
                    FixOption(id="leave", label="Leave as is", step=None),
                ],
            )
        )

    return issues
