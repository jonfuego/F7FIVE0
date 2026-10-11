"""Artist name matching shared by the keyless art sources.

Library names and catalog names disagree on small things: "Edward KaSpel" vs
"Edward Ka-Spel", "The Birthday Party" vs "Birthday Party", "Beyonce" vs
"Beyonce with an accent", "Simon & Garfunkel" vs "Simon and Garfunkel". `match_key`
folds all of that away so two names are the same artist when their keys are
equal. It is deliberately not fuzzy: a picture on the wrong artist is worse
than no picture, so anything that is not an exact match after folding is
rejected.
"""
from __future__ import annotations

import re
import unicodedata


_AND_RE = re.compile(r"\s*&\s*|\s+and\s+", re.IGNORECASE)


def match_key(name: str, *, drop_the: bool = True) -> str:
    """Fold a name for comparison: no accents, case, punctuation, spacing, a
    leading "the" (unless `drop_the` is false), or "&" vs "and". Empty string
    when nothing is left."""
    if not isinstance(name, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in decomposed if not unicodedata.combining(c))
    text = _AND_RE.sub(" and ", text.casefold())
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    # Drop a leading "the" only when a name remains ("The The" keeps one).
    if drop_the and len(words) > 1 and words[0] == "the":
        words = words[1:]
    return "".join(ch for ch in "".join(words) if ch.isalnum())


def same_artist(a: str, b: str, *, drop_the: bool = True) -> bool:
    key = match_key(a, drop_the=drop_the)
    return bool(key) and key == match_key(b, drop_the=drop_the)
