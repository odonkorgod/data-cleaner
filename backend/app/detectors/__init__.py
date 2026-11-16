"""Issue detectors.

A detector is a function ``(DataFrame) -> list[Issue]``. To add a new one, write the function
in its own module, then register it in ``DETECTORS`` below.
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

Detector = Callable[[pd.DataFrame], list[Issue]]

DETECTORS: list[Detector] = [
    detect_missing,
    detect_inconsistent,
    detect_invalid,
    detect_outliers,
    detect_type_mismatch,
    detect_duplicates,
]


def run_detectors(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []
    for detector in DETECTORS:
        issues.extend(detector(df))
    return issues
