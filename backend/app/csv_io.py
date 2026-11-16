"""Reading and writing CSV bytes. Nothing here touches the disk.

Every cell is read as text, and only empty cells count as missing. That way a file the user
did not ask to change comes back unchanged: leading zeros, "NA" country codes and integer
formatting all survive. Numeric work (mean, median) converts on demand; see ``numeric_values``.

The delimiter, encoding and line endings of the upload are remembered in ``CsvFormat`` and
reused when writing, so the cleaned file has the same shape as the original.
"""

import codecs
import csv
import io
import json
import warnings
from dataclasses import dataclass
from itertools import islice

import pandas as pd
from charset_normalizer import from_bytes

# Delimiters we consider, in order of preference when two fit equally well.
DELIMITERS = (",", ";", "\t", "|")
# Rows inspected when choosing a delimiter.
SNIFF_ROWS = 100


class CsvReadError(ValueError):
    """The upload could not be parsed. Messages never include file contents."""


@dataclass(frozen=True)
class CsvFormat:
    delimiter: str = ","
    encoding: str = "utf-8"
    line_terminator: str = "\n"


def _detect_encoding(raw: bytes) -> str:
    if raw.startswith(codecs.BOM_UTF8):
        # utf-8-sig strips the BOM on read and writes it back on write.
        return "utf-8-sig"
    best = from_bytes(raw).best()
    return best.encoding if best is not None else "utf-8"


def _detect_delimiter(text: str) -> str:
    """Pick the delimiter that splits the header into the most fields, consistently.

    A delimiter qualifies when the header has at least two fields and every sampled row has
    the same number of fields. If none qualifies, the file is either a single column (use a
    comma, which is then harmless) or ragged, in which case the delimiter that splits the
    header most wins and the parser reports any bad rows.
    """
    best, best_width = ",", 1
    fallback, fallback_width = ",", 1
    for delimiter in DELIMITERS:
        try:
            rows = islice(csv.reader(io.StringIO(text), delimiter=delimiter), SNIFF_ROWS)
            widths = [len(row) for row in rows if row]
        except csv.Error:
            continue
        if not widths or widths[0] < 2:
            continue
        if all(w == widths[0] for w in widths) and widths[0] > best_width:
            best, best_width = delimiter, widths[0]
        if widths[0] > fallback_width:
            fallback, fallback_width = delimiter, widths[0]
    return best if best_width > 1 else fallback


def _detect_line_terminator(text: str) -> str:
    newline = text.find("\n")
    return "\r\n" if newline > 0 and text[newline - 1] == "\r" else "\n"


def read_csv(raw: bytes) -> tuple[pd.DataFrame, CsvFormat]:
    if not raw.strip():
        raise CsvReadError("The file is empty.")

    encoding = _detect_encoding(raw)
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        raise CsvReadError("Could not detect the file's text encoding.") from None

    fmt = CsvFormat(
        delimiter=_detect_delimiter(text),
        encoding=encoding,
        line_terminator=_detect_line_terminator(text),
    )

    try:
        with warnings.catch_warnings():
            # Rows with more fields than the header would otherwise lose data silently.
            warnings.simplefilter("error", pd.errors.ParserWarning)
            df = pd.read_csv(
                io.StringIO(text),
                sep=fmt.delimiter,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
                index_col=False,
            )
    except pd.errors.ParserWarning:
        raise CsvReadError("Some rows have more fields than the header row.") from None
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError):
        # Deliberately generic: pandas errors can echo fragments of the data.
        raise CsvReadError(
            "Could not parse this file as CSV. Check the delimiter, encoding and quoting."
        ) from None

    if df.columns.empty:
        raise CsvReadError("No columns found in the file.")
    return df, fmt


def write_csv(df: pd.DataFrame, fmt: CsvFormat) -> tuple[bytes, str]:
    """Serialize in the upload's format. Returns the bytes and the encoding actually used.

    Falls back to UTF-8 when a filled-in value cannot be represented in the original encoding.
    """
    text = df.to_csv(index=False, sep=fmt.delimiter, lineterminator=fmt.line_terminator)
    encoding = fmt.encoding
    if codecs.lookup(encoding).name == "ascii":
        encoding = "utf-8"  # same bytes for ASCII content, and never fails
    try:
        return text.encode(encoding), encoding
    except UnicodeEncodeError:
        return text.encode("utf-8"), "utf-8"


def numeric_values(series: pd.Series) -> pd.Series | None:
    """The column's non-missing values as numbers, or None if any of them is not a number."""
    present = series.dropna()
    if present.empty:
        return None
    numbers = pd.to_numeric(present, errors="coerce")
    if numbers.isna().any():
        return None
    return numbers.astype(float)


def to_json_records(df: pd.DataFrame) -> list[dict]:
    """Convert rows to JSON-safe dicts (NaN becomes None, numpy types become Python types)."""
    return json.loads(df.to_json(orient="records"))
