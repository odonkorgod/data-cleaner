"""Short, human-readable snippets for an issue's ``detail`` line. Display only."""

from collections.abc import Iterable

MAX_EXAMPLES = 3
MAX_CHARS = 30


def quoted(values: Iterable[str], limit: int = MAX_EXAMPLES) -> str:
    """'"a", "b", "c"', truncating long values. Quotes keep stray spaces visible."""
    out = []
    for value in list(values)[:limit]:
        text = value if len(value) <= MAX_CHARS else value[: MAX_CHARS - 1] + "…"
        out.append(f'"{text}"')
    return ", ".join(out)
