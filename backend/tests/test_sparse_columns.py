"""Mostly empty columns are removed by default and listed so the user can keep them; blank and
repeated headers are written back as uploaded."""

import json

import pytest

from app.csv_io import read_csv, write_csv
from app.detectors.missing import sparse_columns
from app.models import DropColumns
from app.placeholders import placeholder_frame
from app.transform import TransformError, apply_steps

# "fax" is 3/4 empty (one "N/A"), "notes" exactly half, the last column has no header.
SPARSE = b"id,fax,notes,\n1,,a,\n2,N/A,,\n3,555,b,\n4,,,\n"


def _sparse(raw: bytes):
    df, fmt = read_csv(raw)
    return sparse_columns(df.mask(placeholder_frame(df)), fmt.unnamed)


def test_columns_at_least_half_empty_are_listed_named_first_then_least_empty():
    found = _sparse(SPARSE)
    assert [(c.column, c.missing, c.unnamed) for c in found] == [
        ("notes", 2, False),  # exactly half
        ("fax", 3, False),  # the "N/A" counts as empty
        ("Unnamed: 3", 4, True),
    ]


def test_unnamed_columns_come_last_least_empty_first():
    # Unnamed: 2 is fully empty; Unnamed: 3 has one value; "b" is named but emptier.
    found = _sparse(b"a,b,,\n1,,,x\n2,,,\n3,,,\n4,9,,\n")
    assert [c.column for c in found] == ["b", "Unnamed: 3", "Unnamed: 2"]


def test_columns_under_half_empty_are_kept():
    assert _sparse(b"a,b\n1,\n2,3\n4,5\n") == []


def test_nothing_is_listed_if_every_column_would_go():
    assert _sparse(b"a,b\n1,\n,\n,2\n") == []


def test_header_only_file_lists_nothing():
    assert _sparse(b"a,b\n") == []


def test_drop_columns_step():
    df, _ = read_csv(SPARSE)
    out = apply_steps(df, [DropColumns(columns=["fax", "Unnamed: 3"])])
    assert list(out.columns) == ["id", "notes"]


def test_drop_columns_rejects_unknown_columns_and_dropping_everything():
    df, _ = read_csv(b"a,b\n1,2\n")
    with pytest.raises(TransformError):
        apply_steps(df, [DropColumns(columns=["nope"])])
    with pytest.raises(TransformError):
        apply_steps(df, [DropColumns(columns=["a", "b"])])


# -------------------------------------------------------------------- headers survive


@pytest.mark.parametrize(
    "raw",
    [b"a,,c,\n1,x,3,\n4,y,6,\n", b"a,a,b\n1,2,3\n", b'"a,1",,b\n1,2,3\n'],
    ids=["blank headers", "repeated headers", "quoted header"],
)
def test_headers_are_written_back_as_uploaded(raw):
    df, fmt = read_csv(raw)
    assert write_csv(df, fmt)[0] == raw


def test_blank_header_kept_after_other_columns_are_dropped():
    df, fmt = read_csv(b"a,,c\n1,x,\n2,y,\n")
    out = apply_steps(df, [DropColumns(columns=["c"])])
    assert write_csv(out, fmt)[0] == b"a,\n1,x\n2,y\n"


# ------------------------------------------------------------------------------- API


def test_analyze_and_transform(client):
    files = {"file": ("d.csv", SPARSE, "text/csv")}
    body = client.post("/analyze", files=files).json()
    assert [c["column"] for c in body["sparse_columns"]] == ["notes", "fax", "Unnamed: 3"]
    # Their missing-values issues are still reported, for when the user keeps a column.
    assert "missing:fax" in {i["id"] for i in body["issues"]}

    steps = json.dumps([{"op": "drop_columns", "columns": ["Unnamed: 3", "fax"]}])
    res = client.post("/transform", files=files, data={"steps": steps})
    assert res.content == b"id,notes\n1,a\n2,\n3,b\n4,\n"
