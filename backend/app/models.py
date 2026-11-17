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
# Longest value a user may type for a value in a review. Only bounds request size.
MAX_VALUE_LENGTH = 500

# --------------------------------------------------------------------------- fix steps


class DropColumns(BaseModel):
    """Remove whole columns, e.g. ones that are mostly empty."""

    op: Literal["drop_columns"] = "drop_columns"
    columns: list[str] = Field(min_length=1, max_length=10_000)


class StandardizeValues(BaseModel):
    """Write a text column consistently. See categories.py.

    Values differing only in case or spacing always become one. ``case`` picks how they're
    written; ``keep`` uses each value's most common spelling. ``merge`` folds other values in:
    it maps a value's group key (as listed in the issue's ``review``) to the key it becomes.
    ``rename`` maps a group key to text the user typed, written exactly as typed (case style
    doesn't apply), along with everything merged into that value.
    """

    op: Literal["standardize_values"] = "standardize_values"
    column: str
    case: Literal["keep", "title", "upper", "lower"] = "keep"
    merge: dict[str, str] = Field(default_factory=dict)
    rename: dict[str, str] = Field(default_factory=dict)

    @field_validator("merge")
    @classmethod
    def _bounded(cls, merge: dict[str, str]) -> dict[str, str]:
        if len(merge) > MAX_MERGES:
            raise ValueError(f"at most {MAX_MERGES} merges are allowed")
        return merge

    @field_validator("rename")
    @classmethod
    def _typed_values(cls, rename: dict[str, str]) -> dict[str, str]:
        if len(rename) > MAX_MERGES:
            raise ValueError(f"at most {MAX_MERGES} new values are allowed")
        # Spaces at the ends are dropped: stray spaces are one of the inconsistencies fixed here.
        rename = {key: text.strip() for key, text in rename.items()}
        for text in rename.values():
            if not text:
                raise ValueError("new values must not be empty")
            if len(text) > MAX_VALUE_LENGTH:
                raise ValueError(f"new values must be at most {MAX_VALUE_LENGTH} characters")
        return rename

    @model_validator(mode="after")
    def _merge_or_rename(self) -> "StandardizeValues":
        # A value merged into another takes that value's spelling, so it can't have its own.
        if any(key in self.merge and self.merge[key] != key for key in self.rename):
            raise ValueError("a value cannot be both merged and given a new value")
        return self


class FixTypeMismatch(BaseModel):
    """Deal with text in a column that is otherwise numeric."""

    op: Literal["fix_type_mismatch"] = "fix_type_mismatch"
    column: str
    action: Literal["clear", "drop_rows"]


class FixInvalid(BaseModel):
    """Deal with numbers that break a validity rule: below ``min`` or above ``max``.

    A missing bound means no limit on that side. Clearing leaves the cells empty, so a fill
    for missing values (which runs later) can fill them.
    """

    op: Literal["fix_invalid"] = "fix_invalid"
    column: str
    action: Literal["clear", "drop_rows"]
    min: FiniteFloat | None = None
    max: FiniteFloat | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "FixInvalid":
        if self.min is None and self.max is None:
            raise ValueError("give at least one of min and max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not be greater than max")
        return self


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


class ClearPlaceholders(BaseModel):
    """Make text that stands for a missing value ("N/A", "NULL") a truly empty cell.

    Placeholders count as missing either way (see placeholders.py); without this step, any
    that are still missing after the other fixes are written back as they were.
    """

    op: Literal["clear_placeholders"] = "clear_placeholders"
    column: str


class DropNullRows(BaseModel):
    op: Literal["drop_null_rows"] = "drop_null_rows"
    column: str


class DropDuplicates(BaseModel):
    op: Literal["drop_duplicates"] = "drop_duplicates"
    keep: Literal["first", "last"] = "first"


FixStep = Annotated[
    DropColumns
    | StandardizeValues
    | FixTypeMismatch
    | FixInvalid
    | FixOutliers
    | FillNulls
    | ClearPlaceholders
    | DropNullRows
    | DropDuplicates,
    Field(discriminator="op"),
]

# Steps always run in this order, regardless of the order the user picked them:
#   0. Remove columns first, so no other step spends time on them.
#   1. Fix individual values: spellings, then stray text, then invalid values, then outliers.
#      Invalid values go before outliers so they don't distort the usual range, and all of
#      these go before fills so a mean or median fill isn't skewed by them.
#   2. Fill gaps, then drop rows that still have gaps.
#   3. Drop duplicates last, so rows made identical by earlier fixes are caught.
STEP_ORDER: dict[str, int] = {
    "drop_columns": 0,
    "standardize_values": 1,
    "fix_type_mismatch": 2,
    "fix_invalid": 3,
    "fix_outliers": 4,
    "fill_nulls": 10,
    "clear_placeholders": 15,
    "drop_null_rows": 20,
    "drop_duplicates": 30,
}

# ----------------------------------------------------------------------- issue reports

# The groups the UI summarises issues under.
Category = Literal[
    "missingness", "inconsistent", "invalid", "outliers", "type_mismatch", "duplicates"
]


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
    """One distinct value of a text column, for the user to review, merge or rewrite."""

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


class ValidityRule(BaseModel):
    """The rule an invalid-values issue was found with. The user can edit it."""

    min: float | None
    max: float | None
    reason: str
    source: Literal["name", "data"]  # suggested from the column name, or from the data


class NumberSummary(BaseModel):
    """A number column's distribution, so the UI can preview rules the user adds."""

    values: int
    quantiles: list[float]  # the value at every half percentile, 0 to 100 (201 entries)


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
    # Invalid-values issues only: the rule the values break.
    rule: ValidityRule | None = None


class SparseColumn(BaseModel):
    """A mostly empty column, removed unless the user keeps it."""

    column: str
    missing: int  # empty cells, placeholders like "N/A" included
    unnamed: bool  # the header cell was blank (pandas calls it "Unnamed: 3")


class AnalyzeResponse(BaseModel):
    rows: int
    columns: list[str]
    issues: list[Issue]
    # Columns removed by default for being mostly empty: named first, then unnamed, each least
    # empty first. Their issues are still listed, for when the user keeps them.
    sparse_columns: list[SparseColumn] = Field(default_factory=list)
    # Number columns the user can add a validity rule to (not IDs or codes), by name.
    numbers: dict[str, NumberSummary] = Field(default_factory=dict)
