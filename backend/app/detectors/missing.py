"""Detect columns that contain missing values."""

import pandas as pd
from pandas.api.types import is_numeric_dtype

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.models import FixOption, Issue


def detect_missing(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []

    for column in df.columns:
        mask = df[column].isna()
        count = int(mask.sum())
        if count == 0:
            continue

        fixes = [
            FixOption(
                id="drop_rows",
                label="Drop rows with a missing value",
                step={"op": "drop_null_rows", "column": column},
            ),
        ]
        if is_numeric_dtype(df[column]):
            for strategy in ("mean", "median"):
                fixes.append(
                    FixOption(
                        id=f"fill_{strategy}",
                        label=f"Fill with the {strategy}",
                        step={"op": "fill_nulls", "column": column, "strategy": strategy},
                    )
                )
        fixes.append(
            FixOption(
                id="fill_mode",
                label="Fill with the most common value",
                step={"op": "fill_nulls", "column": column, "strategy": "mode"},
            )
        )
        fixes.append(
            FixOption(
                id="fill_constant",
                label="Fill with a value I choose",
                step={"op": "fill_nulls", "column": column, "strategy": "constant"},
                needs_value=True,
            )
        )
        fixes.append(FixOption(id="leave", label="Leave as is", step=None))

        issues.append(
            Issue(
                id=f"missing:{column}",
                type="missing_values",
                title=f"Missing values in '{column}'",
                columns=[str(column)],
                count=count,
                samples=to_json_records(df[mask].head(SAMPLE_ROWS)),
                fixes=fixes,
            )
        )

    return issues
