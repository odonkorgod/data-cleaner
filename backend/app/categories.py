"""Standardizing categorical text: case style, spelling variants, and merges.

How a column is standardized (``standardize_mapping``):

1. Values are grouped by ``normalize_text``: trimmed, single-spaced, case-insensitive. So
   "New York", "new york" and " NEW YORK" are one group, written one way.
2. Groups the user (or a suggestion) merges are folded into their target group.
3. Each group is written in the chosen case style, starting from its representative spelling.

Merges are keyed by group key, not by spelling, so they stay valid whatever case style is
chosen. Case conversion has guards against damaging values that are already right:

* Deliberately mixed-case values ("eBay", "iPhone", "McDonald", "O'Neil") are never changed.
* In Title Case, short all-caps values ("USA", "UK", "NASA") and all-caps words inside a value
  ("NYC Office") are kept, and small words ("of", "de") stay lowercase ("Bank of America").
* Words are capitalized at the first letter only, so "they're" becomes "They're", not
  "They'Re" as Python's str.title() would write it.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.values import normalize_text

CaseStyle = Literal["keep", "title", "upper", "lower"]
CASE_STYLES: tuple[CaseStyle, ...] = ("keep", "title", "upper", "lower")

# Columns with more distinct values than this get no value list; they are only cleaned of
# case and spacing variants.
MAX_REVIEW_VALUES = 100
# An all-caps value with at most this many letters and no spaces is taken to be an acronym.
MAX_ACRONYM_LETTERS = 4
# Lowercase in Title Case unless they start the value.
SMALL_WORDS = frozenset(
    "a an and as at but by for in nor of on or the to via vs de del der des di du la le van von"
    .split()
)

ValueCase = Literal["upper", "lower", "title", "mixed", "inverted", "other"]


# ------------------------------------------------------------------------------- case


_NON_LETTERS = re.compile(r"[\W\d_]+")


def _letters(text: str) -> str:
    return _NON_LETTERS.sub("", text)


def _is_acronym(word: str) -> bool:
    letters = _letters(word)
    return 2 <= len(letters) <= MAX_ACRONYM_LETTERS and letters.isupper()


def _is_inverted(word: str) -> bool:
    """Caps-lock typing: "nEW" (first letter lower, the rest upper)."""
    letters = _letters(word)
    return len(letters) >= 2 and letters[0].islower() and letters[1:].isupper()


def _is_title_word(word: str, first: bool) -> bool:
    if not first and word in SMALL_WORDS:
        return True
    for part in word.split("-"):
        letters = _letters(part)
        if not letters:
            continue
        if not (letters[0].isupper() and letters[1:] == letters[1:].lower()):
            return _is_acronym(part)  # "NYC" inside "NYC Office" still reads as Title Case
    return True


def _has_inner_capital(part: str) -> bool:
    """A capital after the first letter: "eBay", "iPhone", "McDonald", "O'Neil".

    All-caps words (acronyms) and caps-lock typing ("nEW") don't count.
    """
    letters = _letters(part)
    return not letters.isupper() and not _is_inverted(part) and any(
        c.isupper() for c in letters[1:]
    )


def value_case(value: str) -> ValueCase | None:
    """How a value is capitalized, or None when it has no letters (e.g. "42").

    * ``upper`` / ``lower``: every letter is.
    * ``title``: every word capitalized, small words and acronyms allowed ("Bank of America").
    * ``mixed``: deliberate capitals inside a word ("eBay", "McDonald"). Never converted.
    * ``inverted``: caps-lock typing ("nEW yORK").
    * ``other``: anything else, e.g. "New york" or "NYC office".
    """
    letters = _letters(value)
    if not letters:
        return None
    if letters.isupper():
        return "upper"
    if letters.islower():
        return "lower"
    words = value.split()
    if any(_is_inverted(w) for w in words):
        return "inverted"
    if any(_has_inner_capital(part) for w in words for part in w.split("-")):
        return "mixed"
    if all(_is_title_word(w, i == 0) for i, w in enumerate(words)):
        return "title"
    return "other"


def case_style(series: pd.Series) -> CaseStyle:
    """The column's most common case style, by number of cells.

    Mixed-case values and values without letters don't vote. Ties prefer Title Case, then
    upper, then lower. A column with no voting values is left as it is.
    """
    votes = {"title": 0, "upper": 0, "lower": 0}
    for value, count in series.dropna().value_counts().items():
        style = value_case(str(value))
        if style in votes:
            votes[style] += int(count)
    if not any(votes.values()):
        return "keep"
    return max(votes, key=lambda s: votes[s])  # max() keeps the first on ties


def _capitalize(part: str) -> str:
    """Upper-case the first letter, lower-case the rest: "they're" -> "They're"."""
    for i, c in enumerate(part):
        if c.isalpha():
            return part[:i] + c.upper() + part[i + 1 :].lower()
    return part


def _title_case(text: str, keep_acronyms: bool) -> str:
    words = []
    for i, word in enumerate(text.split(" ")):
        if keep_acronyms and _is_acronym(word):
            words.append(word)
        elif i > 0 and word.lower() in SMALL_WORDS:
            words.append(word.lower())
        else:
            words.append("-".join(_capitalize(p) for p in word.split("-")))
    return " ".join(words)


def apply_case(value: str, style: CaseStyle) -> str:
    """Write a value in a case style, with spacing tidied. See the module docstring."""
    text = " ".join(value.split())
    if style == "keep":
        return text
    kind = value_case(text)
    if kind in (None, "mixed"):
        return text
    if style == "upper":
        return text.upper()
    if style == "lower":
        return text.lower()
    if kind == "upper" and " " not in text and _is_acronym(text):
        return text  # "USA"
    # In an all-caps value every word is shouting, not an acronym: "NEW YORK" -> "New York".
    return _title_case(text, keep_acronyms=kind != "upper")


# ----------------------------------------------------------------------------- groups


@dataclass
class ValueGroup:
    key: str
    count: int = 0
    # (spelling, cells), most common first. Ties go to the spelling in the column's usual case
    # style, then to the one that appears first.
    spellings: list[tuple[str, int]] = field(default_factory=list)

    @property
    def representative(self) -> str:
        """The spelling the group is written from.

        A deliberately mixed-case spelling ("eBay") wins, so case conversion can't undo it.
        Otherwise the most common spelling.
        """
        if len(self.spellings) == 1:
            return self.spellings[0][0]
        for spelling, _ in self.spellings:
            if value_case(spelling) == "mixed":
                return spelling
        return self.spellings[0][0]

    def display(self, style: CaseStyle) -> str:
        return apply_case(self.representative, style)


def group_values(series: pd.Series) -> dict[str, ValueGroup]:
    """Spelling variants grouped by ``normalize_text``, most common group first."""
    present = series.dropna().astype(str)
    counts = present.value_counts(sort=False).to_dict()  # dict lookups are much faster
    groups: dict[str, ValueGroup] = {}
    for spelling in present.drop_duplicates():  # order of first appearance
        key = normalize_text(spelling)
        group = groups.get(key)
        if group is None:
            group = groups[key] = ValueGroup(key)
        cells = int(counts[spelling])
        group.count += cells
        group.spellings.append((spelling, cells))
    usual: CaseStyle | None = None  # worked out only if some spellings tie
    for group in groups.values():
        if len(group.spellings) < 2:
            continue
        counts_seen = [n for _, n in group.spellings]
        if len(set(counts_seen)) == len(counts_seen):
            group.spellings.sort(key=lambda s: -s[1])
            continue
        if usual is None:
            usual = case_style(series)
        # Stable sort: among equally common spellings in the usual style, first seen wins.
        group.spellings.sort(key=lambda s: (-s[1], value_case(s[0]) != usual))
    return dict(sorted(groups.items(), key=lambda kv: -kv[1].count))


# ------------------------------------------------------------------------ suggestions


def _squash(key: str) -> str:
    """Letters and digits only, so "n.y." and "ny" compare equal."""
    return re.sub(r"[\W_]+", "", key)


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Optimal string alignment distance (a swap of neighbours counts as one edit).

    Returns ``limit + 1`` as soon as the distance is known to exceed ``limit``.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], prev2[j - 2] + 1)
        if min(row) > limit:
            return limit + 1
        prev2, prev = prev, row
    return prev[-1]


def _is_typo_of(a: str, b: str) -> bool:
    """Whether word ``a`` looks like a typo of word ``b``.

    Short words are strict, since a one-letter change there is usually a different word
    ("Gold"/"Bold"): nothing under 4 letters, only swapped neighbours at 4 ("Yrok"/"York").
    Longer words allow one edit, and two from 9 letters. The shorter word sets the allowance,
    so "Austria" (7) is not a typo of "Australia" (9).
    """
    shortest = min(len(a), len(b))
    if shortest < 4:
        return False
    if shortest == 4:
        return len(a) == len(b) and sorted(a) == sorted(b) and _edit_distance(a, b, 1) == 1
    limit = 1 if shortest <= 8 else 2
    return _edit_distance(a, b, limit) <= limit


def _similar(a: str, b: str) -> bool:
    """Two group keys that differ only by typos in words long enough to judge."""
    if re.sub(r"\D", "", a) != re.sub(r"\D", "", b):
        return False  # "Room 101" and "Room 102" are different rooms
    words_a, words_b = a.split(), b.split()
    if len(words_a) != len(words_b):
        return False
    differing = [(x, y) for x, y in zip(words_a, words_b, strict=True) if x != y]
    return bool(differing) and all(_is_typo_of(x, y) for x, y in differing)


@dataclass(frozen=True)
class Suggestion:
    target: str  # key of the group to merge into
    reason: str


def suggest_merges(groups: dict[str, ValueGroup]) -> dict[str, Suggestion]:
    """Suggest merging rare near-duplicates into a more common group.

    Groups are visited most common first; each may be merged into a group seen before it
    (so the more common spelling wins) that is not itself being merged (so there are no
    chains). Same letters with different punctuation ("N.Y." / "NY") is the strongest match,
    then typos.
    """
    suggestions: dict[str, Suggestion] = {}
    kept: list[ValueGroup] = []
    for group in groups.values():
        squashed = _squash(group.key)
        match = None
        for target in kept:
            if squashed and squashed == _squash(target.key):
                match = Suggestion(target.key, "Same letters, different punctuation")
                break
            if match is None and _similar(group.key, target.key):
                match = Suggestion(target.key, "Similar spelling")
        if match:
            suggestions[group.key] = match
        else:
            kept.append(group)
    return suggestions


# ---------------------------------------------------------------------------- mapping


class MergeError(ValueError):
    """Merges name a value that isn't in the column, or loop. Never includes values."""


def _resolve(merge: dict[str, str], groups: dict[str, ValueGroup]) -> dict[str, str]:
    """Follow chains (a -> b -> c becomes a -> c); reject unknown values and loops."""
    if any(k not in groups or v not in groups for k, v in merge.items()):
        raise MergeError("unknown value")
    resolved: dict[str, str] = {}
    for key in merge:
        seen, target = {key}, merge[key]
        while target in merge and merge[target] != target:
            if target in seen:
                raise MergeError("loop")
            seen.add(target)
            target = merge[target]
        resolved[key] = target
    return resolved


def standardize_mapping(
    series: pd.Series,
    style: CaseStyle,
    merge: dict[str, str] | None = None,
    groups: dict[str, ValueGroup] | None = None,
) -> dict[str, str]:
    """Map each spelling that changes to its standardized value.

    ``merge`` maps group keys (see ``group_values``) to the group key they should become.
    Pass ``groups`` if already computed for this series, to avoid grouping twice.
    """
    groups = groups if groups is not None else group_values(series)
    resolved = _resolve(merge or {}, groups)
    mapping: dict[str, str] = {}
    for group in groups.values():
        target = groups[resolved.get(group.key, group.key)]
        new = target.display(style)
        for spelling, _ in group.spellings:
            if spelling != new:
                mapping[spelling] = new
    return mapping
