"""Pydantic models: the contract between detectors, the API, and the frontend.

Two families live here:

* Issues + fix options: what ``/analyze`` returns to the user.
* Fix steps: what the user sends back to ``/transform``. Each step is a small JSON object
  discriminated by ``op``. The frontend mirrors these in ``frontend/src/types.ts``.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

# --------------------------------------------------------------------------- fix steps


class StandardizeValues(BaseModel):
    """Rewrite spelling variants (case, whitespace) to the most common spelling."""

    op: Literal["standardize_values"] = "standardize_values"
    column: str


class FixTypeMismatch(BaseModel):
    """Deal with text in a column that is otherwise numeric."""

    op: Literal["fix_type_mismatch"] = "fix_type_mismatch"
    column: str
    action: Literal["clear", "drop_rows"]


class FixOutliers(BaseModel):
    """Deal with numbers outside ``[lower, upper]``, the usual range found by /analyze."""

    op: Literal["fix_outliers"] = "fix_outliers"
    column: str
    lower: FiniteFloat
    upper: FiniteFloat
    action: Literal["cap", "drop_rows"]

    @model_validator(mode="after")
    def _ordered(self) -> "FixOutliers":
        if self.lower > self.upper:
            raise ValueError("lower must not be greater than upper")
        return self


class FillNulls(BaseModel):
    op: Literal["fill_nulls"] = "fill_nulls"
    column: str
    strategy: Literal["mean", "median", "mode", "constant"]
    # Only used when strategy == "constant".
    value: str | None = None


class DropNullRows(BaseModel):
    op: Literal["drop_null_rows"] = "drop_null_rows"
    column: str


class DropDuplicates(BaseModel):
    op: Literal["drop_duplicates"] = "drop_duplicates"
    keep: Literal["first", "last"] = "first"


FixStep = Annotated[
    StandardizeValues | FixTypeMismatch | FixOutliers | FillNulls | DropNullRows | DropDuplicates,
    Field(discriminator="op"),
]

# Steps always run in this order, regardless of the order the user picked them:
#   1. Fix individual values: spellings, then stray text, then outliers. Outliers are handled
#      before fills so a mean or median fill isn't skewed by them.
#   2. Fill gaps, then drop rows that still have gaps.
#   3. Drop duplicates last, so rows made identical by earlier fixes are caught.
STEP_ORDER: dict[str, int] = {
    "standardize_values": 1,
    "fix_type_mismatch": 2,
    "fix_outliers": 3,
    "fill_nulls": 10,
    "drop_null_rows": 20,
    "drop_duplicates": 30,
}

# ----------------------------------------------------------------------- issue reports

# The groups the UI summarises issues under.
Category = Literal["missingness", "inconsistent", "outliers", "type_mismatch", "duplicates"]


class FixOption(BaseModel):
    """One choice the user can make for an issue."""

    id: str
    label: str
    # Template for the step to send to /transform. ``None`` means "leave as is".
    step: dict[str, Any] | None = None
    # True when the user must supply ``value`` (e.g. fill with a constant).
    needs_value: bool = False
    # True for the option we suggest; the issue's ``detail`` says why.
    recommended: bool = False


class Issue(BaseModel):
    id: str
    type: str
    category: Category
    title: str
    columns: list[str]
    # Affected cells (rows, for duplicates).
    count: int
    # One short line for the summary, e.g. examples of the problem values.
    detail: str | None = None
    samples: list[dict[str, Any]]
    fixes: list[FixOption]


class AnalyzeResponse(BaseModel):
    rows: int
    columns: list[str]
    issues: list[Issue]
