"""Text that stands for a missing value, like "N/A", "NULL" or "#N/A".

The file is read with every cell as text and only truly empty cells missing (see csv_io.py), so
nothing changes unless the user asks. Placeholders are recognized afterwards: detectors and fixes
see them as empty cells, and any placeholder that is still empty after the fixes is written back
exactly as it was uploaded (see ``apply_steps`` in transform.py). So "Leave as is" keeps "N/A",
while filling or dropping missing values covers placeholders too.

Matching ignores case and surrounding spaces. Words that can be real values are only treated
as placeholders in number columns, where text can't be a real value:

* "NA" is Namibia's country code and "North America", "NaN" and "Nan" are names.
* "None", "Nil" and "-" often mean zero ("children: none"), so they are never placeholders
  here. In a number column they show up as a data type mismatch for the user to decide.
"""

import pandas as pd

from app.values import is_mostly_numeric

# Placeholders in any column. "" covers cells that hold only spaces.
ALWAYS = frozenset({"", "null", "(null)", "<null>", "n/a", "#n/a", "<na>", "n.a."})
# Placeholders only in columns whose other values are mostly numbers.
IN_NUMBER_COLUMNS = frozenset(
    {"na", "nan", "missing", "unknown", "?", "not available", "not applicable"}
)


def placeholder_mask(series: pd.Series) -> pd.Series:
    """True for cells holding a placeholder for a missing value (truly empty cells are False)."""
    mask = pd.Series(False, index=series.index)
    present = series.dropna()
    if present.empty:
        return mask
    text = present.astype(str).str.strip().str.casefold()
    found = text.isin(ALWAYS)
    maybe = text.isin(IN_NUMBER_COLUMNS)
    if maybe.any() and is_mostly_numeric(present[~(found | maybe)]):
        found |= maybe
    mask[found[found].index] = True
    return mask


def placeholder_frame(df: pd.DataFrame) -> pd.DataFrame:
    """``placeholder_mask`` for every column."""
    return pd.DataFrame({column: placeholder_mask(df[column]) for column in df.columns})

