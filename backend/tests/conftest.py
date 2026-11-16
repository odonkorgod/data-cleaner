import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def messy_df() -> pd.DataFrame:
    """Small dataset with a missing numeric value, a missing text value, and one duplicate row."""
    return pd.DataFrame(
        {
            "name": ["Ada", "Grace", "Grace", "Linus", None],
            "age": [36.0, 45.0, 45.0, None, 30.0],
        }
    )


@pytest.fixture
def messy_csv(messy_df: pd.DataFrame) -> bytes:
    return messy_df.to_csv(index=False).encode("utf-8")
