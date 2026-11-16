"""Pydantic models: the contract between detectors, the API, and the frontend.

Two families live here:

* Issues + fix options: what ``/analyze`` returns to the user.
* Fix steps: what the user sends back to ``/transform``. Each step is a small JSON object
  discriminated by ``op``. The frontend mirrors these in ``frontend/src/types.ts``.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, FiniteFloat, field_validator, model_validator

# Most merges a single standardize step may carry. The UI lists at most 100 values per column,
# so this is generous; it only bounds request size.
MAX_MERGES = 1000

# --------------------------------------------------------------------------- fix steps


class StandardizeValues(BaseModel):
    """Write a text column consistently. See categories.py.

    Values differing only in case or spacing always become one. ``case`` picks how they're
    written; ``keep`` uses each value's most common spelling. ``merge`` folds other values in:
    it maps a value's group key (as listed in the issue's ``review``) to the key it becomes.
    """

    op: Literal["standardize_values"] = "standardize_values"
    column: str
    case: Literal["keep", "title", "upper", "lower"] = "keep"
    merge: dict[str, str] = Field(default_factory=dict)

    @field_validator("merge")
    @classmethod
    def _bounded(cls, merge: dict[str, str]) -> dict[str, str]:
        if len(merge) > MAX_MERGES:
            raise ValueError(f"at most {MAX_MERGES} merges are allowed")
        return merge


class FixTypeMismatch(BaseModel):
    """Deal with text in a column that is otherwise numeric."""

    op: Literal["fix_type_mismatch"] = "fix_type_mismatch"
    column: str
    action: Literal["clear", "drop_rows"]


class FixOutliers(BaseModel):
    """Cap (winsorize) or drop numbers outside a range.

    The range is given either as values (``lower``/``upper``: the usual range found by
    /analyze, or the user's own) or as percentiles (``lower_pct``/``upper_pct``, worked out
    from the data when the step runs). A missing bound means no limit on that side.
    """

    op: Literal["fix_outliers"] = "fix_outliers"
    column: str
    action: Literal["cap", "drop_rows"]
    lower: FiniteFloat | None = None
    upper: FiniteFloat | None = None
    lower_pct: float | None = Field(default=None, ge=0, le=50)
    upper_pct: float | None = Field(default=None, ge=50, le=100)

    @model_validator(mode="after")
    def _consistent(self) -> "FixOutliers":
        values = self.lower is not None or self.upper is not None
        percentiles = self.lower_pct is not None or self.upper_pct is not None
        if values and percentiles:
            raise ValueError("give the range as values or as percentiles, not both")
        if not values and not percentiles:
            raise ValueError("give at least one cut-off")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
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


class ReviewValue(BaseModel):
    """One distinct value of a text column, for the user to review and merge."""

    key: str  # identifies the value in a step's ``merge``
    count: int
    # How the value is written under each case style ("keep", "title", "upper", "lower").
    display: dict[str, str]
    # Key of the value we suggest merging this one into, and why.
    suggestion: str | None = None
    reason: str | None = None


class ValueReview(BaseModel):
    """The distinct values of a text column, so the user can choose a case and merge values."""

    case: Literal["keep", "title", "upper", "lower"]  # detected from the column
    values: list[ReviewValue]  # most common first


class OutlierCutoffs(BaseModel):
    """What the UI needs to offer cut-offs for an outlier column, and preview them."""

    # The usual range (suggested cut-offs): exact, and as written in the column.
    lower: float
    upper: float
    lower_text: str
    upper_text: str
    # How many numbers the column has, and the value at every half percentile (0, 0.5, ...,
    # 100: 201 real data values), so the UI can estimate how many rows any cut-off affects.
    values: int
    quantiles: list[float]
    # Percentile cut-offs need enough values to mean anything; their suggested defaults.
    percentiles_ok: bool
    lower_pct: float
    upper_pct: float


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
    # Inconsistent text columns only: the values to review.
    review: ValueReview | None = None
    # Outlier columns only: the suggested cut-offs and data to preview others.
    cutoffs: OutlierCutoffs | None = None


class AnalyzeResponse(BaseModel):
    rows: int
    columns: list[str]
    issues: list[Issue]
