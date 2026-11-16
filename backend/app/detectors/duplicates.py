"""Detect fully duplicated rows."""

import pandas as pd

from app.config import SAMPLE_ROWS
from app.csv_io import to_json_records
from app.models import FixOption, Issue


def detect_duplicates(df: pd.DataFrame) -> list[Issue]:
    # keep=False marks every copy, so samples show the whole duplicate group;
    # the count is the number of *extra* rows a fix would remove.
    extra = int(df.duplicated(keep="first").sum())
    if extra == 0:
        return []

    all_copies = df[df.duplicated(keep=False)]

    return [
        Issue(
            id="duplicates:all",
            type="duplicate_rows",
            title="Duplicate rows",
            columns=[str(c) for c in df.columns],
            count=extra,
            samples=to_json_records(all_copies.head(SAMPLE_ROWS)),
            fixes=[
                FixOption(
                    id="keep_first",
                    label="Keep the first copy, drop the rest",
                    step={"op": "drop_duplicates", "keep": "first"},
                ),
                FixOption(
                    id="keep_last",
                    label="Keep the last copy, drop the rest",
                    step={"op": "drop_duplicates", "keep": "last"},
                ),
                FixOption(id="leave", label="Leave as is", step=None),
            ],
        )
    ]
