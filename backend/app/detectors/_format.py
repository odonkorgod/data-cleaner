"""Short, human-readable snippets for an issue's ``detail`` line. Display only."""

from collections.abc import Iterable

import pandas as pd

MAX_EXAMPLES = 3
MAX_CHARS = 30
# Numbers are shown with at most this many decimals. Display only: fixes use exact values.
DISPLAY_DECIMALS = 2


def quoted(values: Iterable[str], limit: int = MAX_EXAMPLES) -> str:
    """'"a", "b", "c"', truncating long values. Quotes keep stray spaces visible."""
    out = []
    for value in list(values)[:limit]:
        text = value if len(value) <= MAX_CHARS else value[: MAX_CHARS - 1] + "…"
        out.append(f'"{text}"')
    return ", ".join(out)


def short_number(text: str) -> str:
    """Shorten long decimals for display ("1.23571" -> "1.24"); other text is unchanged."""
    whole, dot, decimals = text.partition(".")
    if dot and len(decimals) > DISPLAY_DECIMALS and decimals.isdigit():
        return f"{float(text):.{DISPLAY_DECIMALS}f}"
    return text


def worst_values(series: pd.Series, badness: pd.Series) -> str:
    """'150, 120': the cells with the highest ``badness``, each value once, shortened."""
    order = badness.dropna().sort_values(ascending=False).index
    distinct = dict.fromkeys(short_number(str(series[i])) for i in order)
    return ", ".join(list(distinct)[:MAX_EXAMPLES])
