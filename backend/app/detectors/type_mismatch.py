"""Detect text in columns that are otherwise numeric (e.g. "twenty" or "none" among ages).

Placeholders for missing values ("N/A", "unknown") are reported as missing values instead.
"""

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.detectors._format import quoted
from app.models import FixOption, Issue
from app.values import is_mostly_numeric, non_numeric_mask


def detect_type_mismatch(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []

    for column in df.columns:
        series = df[column]
        if not is_mostly_numeric(series):
            continue
        mask = non_numeric_mask(series)
        count = int(mask.sum())
        if count == 0:
            continue

        examples = series[mask].value_counts().index  # most common first
        issues.append(
            Issue(
                id=f"type_mismatch:{column}",
                type="type_mismatch",
                category="type_mismatch",
                title=f"Text in number column '{column}'",
                columns=[str(column)],
                count=count,
                detail=f"Numbers expected, found {quoted(examples)}",
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                fixes=[
                    FixOption(
                        id="clear",
                        label="Clear them (leave the cells empty)",
                        step={"op": "fix_type_mismatch", "column": column, "action": "clear"},
                    ),
                    FixOption(
                        id="drop_rows",
                        label="Drop rows that have them",
                        step={"op": "fix_type_mismatch", "column": column, "action": "drop_rows"},
                    ),
                    FixOption(id="leave", label="Leave as is", step=None),
                ],
            )
        )

    return issues
