import io
import json

import pandas as pd


def _upload(csv: bytes, name: str = "data.csv"):
    return {"file": (name, csv, "text/csv")}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_analyze_returns_issues(client, messy_csv):
    res = client.post("/analyze", files=_upload(messy_csv))
    assert res.status_code == 200
    body = res.json()
    assert body["rows"] == 5
    assert body["columns"] == ["name", "age"]
    assert {i["type"] for i in body["issues"]} == {"missing_values", "duplicate_rows"}


def test_analyze_clean_file_has_no_issues(client):
    res = client.post("/analyze", files=_upload(b"a,b\n1,x\n2,y\n"))
    assert res.json()["issues"] == []


def test_analyze_rejects_empty_file(client):
    res = client.post("/analyze", files=_upload(b""))
    assert res.status_code == 400


def test_analyze_handles_semicolon_delimiter(client):
    res = client.post("/analyze", files=_upload(b"a;b\n1;x\n2;y\n"))
    assert res.json()["columns"] == ["a", "b"]


def test_analyze_handles_latin1_encoding(client):
    csv = "name,city\nJosé,São Paulo\nZoë,Zürich\n".encode("latin-1")
    res = client.post("/analyze", files=_upload(csv))
    assert res.status_code == 200
    assert res.json()["rows"] == 2


def test_upload_over_the_size_limit_is_rejected(client, monkeypatch):
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 10)
    res = client.post("/analyze", files=_upload(b"a,b\n" + b"1,2\n" * 20))
    assert res.status_code == 413


def test_transform_applies_steps_and_returns_csv(client, messy_csv):
    steps = [
        {"op": "fill_nulls", "column": "age", "strategy": "median"},
        {"op": "drop_null_rows", "column": "name"},
        {"op": "drop_duplicates", "keep": "first"},
    ]
    res = client.post("/transform", files=_upload(messy_csv), data={"steps": json.dumps(steps)})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert res.headers["cache-control"] == "no-store"

    out = pd.read_csv(io.BytesIO(res.content))
    assert list(out["name"]) == ["Ada", "Grace", "Linus"]
    assert out["age"].isna().sum() == 0


def test_transform_with_no_steps_returns_the_data_unchanged(client, messy_csv):
    res = client.post("/transform", files=_upload(messy_csv))
    out = pd.read_csv(io.BytesIO(res.content))
    assert len(out) == 5


def test_transform_rejects_unknown_ops(client, messy_csv):
    steps = json.dumps([{"op": "rm_rf"}])
    res = client.post("/transform", files=_upload(messy_csv), data={"steps": steps})
    assert res.status_code == 422


def test_transform_validation_errors_do_not_echo_input(client, messy_csv):
    secret = "SUPER-SECRET-VALUE"
    steps = json.dumps([{"op": "fill_nulls", "column": "name", "strategy": secret}])
    res = client.post("/transform", files=_upload(messy_csv), data={"steps": steps})
    assert res.status_code == 422
    assert secret not in res.text


def test_transform_bad_column_returns_422(client, messy_csv):
    steps = json.dumps([{"op": "drop_null_rows", "column": "missing_col"}])
    res = client.post("/transform", files=_upload(messy_csv), data={"steps": steps})
    assert res.status_code == 422
    assert "missing_col" in res.json()["detail"]
