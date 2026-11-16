"""Reading and writing CSV bytes. Nothing here touches the disk."""

import io
import json

import pandas as pd
from charset_normalizer import from_bytes


class CsvReadError(ValueError):
    """The upload could not be parsed. Messages never include file contents."""


def read_csv(raw: bytes) -> pd.DataFrame:
    if not raw.strip():
        raise CsvReadError("The file is empty.")

    best = from_bytes(raw).best()
    encoding = best.encoding if best is not None else "utf-8"

    try:
        # sep=None lets pandas sniff the delimiter (comma, semicolon, tab, pipe).
        df = pd.read_csv(
            io.BytesIO(raw),
            sep=None,
            engine="python",
            encoding=encoding,
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError):
        # Deliberately generic: pandas errors can echo fragments of the data.
        raise CsvReadError(
            "Could not parse this file as CSV. Check the delimiter, encoding and quoting."
        ) from None

    if df.columns.empty:
        raise CsvReadError("No columns found in the file.")
    return df


def write_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_json_records(df: pd.DataFrame) -> list[dict]:
    """Convert rows to JSON-safe dicts (NaN becomes None, numpy types become Python types)."""
    return json.loads(df.to_json(orient="records"))
