"""Issue detectors.

A detector is a function ``(DataFrame) -> list[Issue]``. To add a new one, write the function
in its own module, then register it in ``DETECTORS`` below.
"""

from collections.abc import Callable

import pandas as pd

from app.detectors.duplicates import detect_duplicates
from app.detectors.missing import detect_missing
from app.models import Issue

Detector = Callable[[pd.DataFrame], list[Issue]]

DETECTORS: list[Detector] = [
    detect_missing,
    detect_duplicates,
]


def run_detectors(df: pd.DataFrame) -> list[Issue]:
    issues: list[Issue] = []
    for detector in DETECTORS:
        issues.extend(detector(df))
    return issues
