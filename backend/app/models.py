"""Pydantic models: the contract between detectors, the API, and the frontend.

Two families live here:

* Issues + fix options: what ``/analyze`` returns to the user.
* Fix steps: what the user sends back to ``/transform``. Each step is a small JSON object
  discriminated by ``op``. The frontend mirrors these in ``frontend/src/types.ts``.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- fix steps


class DropNullRows(BaseModel):
    op: Literal["drop_null_rows"] = "drop_null_rows"
    column: str


class FillNulls(BaseModel):
    op: Literal["fill_nulls"] = "fill_nulls"
    column: str
    strategy: Literal["mean", "median", "mode", "constant"]
    # Only used when strategy == "constant".
    value: str | None = None


class DropDuplicates(BaseModel):
    op: Literal["drop_duplicates"] = "drop_duplicates"
    keep: Literal["first", "last"] = "first"


FixStep = Annotated[
    DropNullRows | FillNulls | DropDuplicates,
    Field(discriminator="op"),
]

# Steps always run in this order, regardless of the order the user picked them.
# Cleaning values comes before removing rows, and duplicates are checked last so that
# rows made identical by earlier fixes are caught.
STEP_ORDER: dict[str, int] = {
    "fill_nulls": 10,
    "drop_null_rows": 20,
    "drop_duplicates": 30,
}

# ----------------------------------------------------------------------- issue reports


class FixOption(BaseModel):
    """One choice the user can make for an issue."""

    id: str
    label: str
    # Template for the step to send to /transform. ``None`` means "leave as is".
    step: dict[str, Any] | None = None
    # True when the user must supply ``value`` (e.g. fill with a constant).
    needs_value: bool = False


class Issue(BaseModel):
    id: str
    type: str
    title: str
    columns: list[str]
    count: int
    samples: list[dict[str, Any]]
    fixes: list[FixOption]


class AnalyzeResponse(BaseModel):
    rows: int
    columns: list[str]
    issues: list[Issue]
