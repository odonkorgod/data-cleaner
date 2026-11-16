"""Issue detectors.

A detector is a function ``(DataFrame) -> list[Issue]``. To add a new one, write the function
in its own module, then register it in ``DETECTORS`` below.

Detectors in ``DETECTORS`` see placeholders like "N/A" as the empty cells they stand for. Only the
missing-values detector sees them as written, so it can tell the user which ones it found.
"""

from collections.abc import Callable

import pandas as pd

from app.detectors.duplicates import detect_duplicates
from app.detectors.inconsistent import detect_inconsistent
from app.detectors.invalid import detect_invalid
from app.detectors.missing import detect_missing
from app.detectors.outliers import detect_outliers
from app.detectors.type_mismatch import detect_type_mismatch
from app.models import Issue
from app.placeholders import placeholder_frame

Detector = Callable[[pd.DataFrame], list[Issue]]

DETECTORS: list[Detector] = [
    detect_inconsistent,
    detect_invalid,
    detect_outliers,
    detect_type_mismatch,
    detect_duplicates,
]


def run_detectors(df: pd.DataFrame, placeholders: pd.DataFrame | None = None) -> list[Issue]:
    """``placeholders`` is ``placeholder_frame(df)``, if the caller already has it."""
    if placeholders is None:
        placeholders = placeholder_frame(df)
    issues = detect_missing(df, placeholders)
    blanked = df.mask(placeholders)
    for detector in DETECTORS:
        issues.extend(detector(blanked))
    return issues
