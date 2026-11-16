from collections.abc import Callable

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.csv_io import read_csv
from app.main import app

# A missing numeric value, a missing text value, and one duplicate row.
MESSY_CSV = b"name,age\nAda,36\nGrace,45\nGrace,45\nLinus,\n,30\n"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def make_df() -> Callable[[str], pd.DataFrame]:
    """Build a DataFrame the way the app does: through read_csv, so every cell is text."""

    def _make(text: str) -> pd.DataFrame:
        df, _ = read_csv(text.encode("utf-8"))
        return df

    return _make


@pytest.fixture
def messy_csv() -> bytes:
    return MESSY_CSV


@pytest.fixture
def messy_df() -> pd.DataFrame:
    df, _ = read_csv(MESSY_CSV)
    return df
