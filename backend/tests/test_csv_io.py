import pytest

from app.csv_io import CsvFormat, CsvReadError, read_csv, write_csv


def roundtrip(raw: bytes) -> bytes:
    df, fmt = read_csv(raw)
    content, _ = write_csv(df, fmt)
    return content


# ---------------------------------------------------------------------- delimiter detection


@pytest.mark.parametrize(
    "raw, columns",
    [
        (b"email\na@x.com\nb@y.com\n", ["email"]),
        (b"id\n1\n2\n3\n", ["id"]),
        (b'name\n"Smith, J"\nAda\n', ["name"]),
    ],
)
def test_single_column_files_keep_their_header(raw, columns):
    df, fmt = read_csv(raw)
    assert list(df.columns) == columns
    assert fmt.delimiter == ","


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_detects_common_delimiters(delimiter):
    raw = delimiter.join(["a", "b", "c"]) + "\n" + delimiter.join(["1", "2", "3"]) + "\n"
    df, fmt = read_csv(raw.encode())
    assert fmt.delimiter == delimiter
    assert list(df.columns) == ["a", "b", "c"]


def test_other_delimiters_inside_values_do_not_confuse_detection():
    df, fmt = read_csv(b"name,notes\nAda,a;b;c\nGrace,x;y;z\n")
    assert fmt.delimiter == ","
    assert df.loc[0, "notes"] == "a;b;c"


def test_rows_with_extra_fields_are_rejected_not_silently_truncated():
    with pytest.raises(CsvReadError, match="more fields than the header"):
        read_csv(b"name\nSmith, J\nAda, L\n")


# ------------------------------------------------------------------ values are kept as text


def test_only_empty_cells_count_as_missing():
    df, _ = read_csv(b"country,code\nNamibia,NA\nnobody,N/A\nNone,null\nempty,\n")
    assert df["code"].isna().tolist() == [False, False, False, True]
    assert df.loc[2, "country"] == "None"


def test_leading_zeros_survive():
    df, _ = read_csv(b"zip,city\n00123,A\n02134,B\n")
    assert df["zip"].tolist() == ["00123", "02134"]


# ------------------------------------------------------------- unchanged files round-trip


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"id,age\n1,36\n2,\n3,40\n", id="integer column with blanks"),
        pytest.param(b"zip,city\n00123,A\n02134,B\n", id="leading zeros"),
        pytest.param(b"country,code\nNamibia,NA\nnobody,N/A\nNone,null\n", id="NA-like text"),
        pytest.param(b"a;b\n1;x\n2;y\n", id="semicolons"),
        pytest.param(b"a\tb\n1\tx\n2\ty\n", id="tabs"),
        pytest.param(b"a,b\r\n1,x\r\n2,y\r\n", id="CRLF line endings"),
        pytest.param(b"\xef\xbb\xbfa,b\n1,x\n", id="UTF-8 with BOM"),
        pytest.param("name,city\nJosé,São Paulo\nZoë,Zürich\n".encode("latin-1"), id="latin-1"),
        pytest.param(b'name,notes\n"Smith, J","said ""hi"""\n', id="quoted fields"),
        pytest.param(b"x,y\n1.50,a\n1e3,b\n", id="number formatting"),
    ],
)
def test_reading_then_writing_returns_identical_bytes(raw):
    assert roundtrip(raw) == raw


def test_bom_is_not_part_of_the_first_column_name():
    df, _ = read_csv(b"\xef\xbb\xbfa,b\n1,x\n")
    assert list(df.columns) == ["a", "b"]


def test_falls_back_to_utf8_when_a_value_does_not_fit_the_original_encoding():
    df, fmt = read_csv("name\nJosé\n".encode("latin-1"))
    df.loc[0, "name"] = "東京"
    content, encoding = write_csv(df, fmt)
    assert encoding == "utf-8"
    assert content.decode("utf-8") == "name\n東京\n"


def test_ascii_files_are_written_as_utf8():
    df, fmt = read_csv(b"a,b\n1,x\n")
    df.loc[0, "b"] = "é"
    _, encoding = write_csv(df, CsvFormat(delimiter=",", encoding="ascii"))
    assert encoding == "utf-8"


# ---------------------------------------------- "\r" line endings (old Mac, Excel for Mac)


@pytest.mark.parametrize(
    "raw",
    [b"a;b;c\r1;2;3\r4;5;6\r", b"a,,c\r1,x,3\r", b'name,note\r\n1,"line one\nline two"\r\n'],
    ids=["semicolons", "blank header", "line break in a quoted cell"],
)
def test_any_line_endings_parse_and_round_trip(raw):
    df, fmt = read_csv(raw)
    assert len(df.columns) > 1  # the delimiter was found
    assert write_csv(df, fmt)[0] == raw


def test_cr_line_endings_get_the_right_delimiter():
    df, fmt = read_csv(b"a;b;c\r1;2;3\r")
    assert fmt.delimiter == ";" and fmt.line_terminator == "\r"
    assert df.loc[0, "b"] == "2"


def test_analyze_accepts_cr_line_endings(client):
    res = client.post("/analyze", files={"file": ("d.csv", b"a,,c\r1,,3\r2,,\r", "text/csv")})
    assert res.status_code == 200
    assert res.json()["columns"] == ["a", "Unnamed: 1", "c"]
