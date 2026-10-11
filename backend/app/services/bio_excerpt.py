"""A short artist bio excerpt for the Home hero.

`bio_excerpt(text)` keeps the first one or two sentences of a bio, at most
`limit` characters, cut at a sentence end. When even the first sentence is
longer than the limit it is cut at a word and ends with an ellipsis. Pure:
no database, no network.
"""
from __future__ import annotations

import re
from typing import Optional

DEFAULT_LIMIT = 220
MAX_SENTENCES = 2

# Words that end in a period without ending the sentence.
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "st", "jr", "sr", "vs", "etc", "no", "inc",
    "ltd", "co", "feat", "ft", "mt", "prof", "vol", "approx", "ca",
})

_CLOSERS = "\"'”’)]"
_WORD_BEFORE = re.compile(r"([A-Za-z]+)$")


def _sentence_ends(text: str) -> list[int]:
    """Index just past each sentence end in `text`. A period ends a sentence
    when whitespace and then something that is not a lowercase letter follows
    (or the text ends), and it does not close an abbreviation or an initial
    such as the "J." in "J. Cole"."""
    ends: list[int] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch not in ".!?":
            i += 1
            continue
        j = i + 1
        while j < n and text[j] in ".!?":
            j += 1
        while j < n and text[j] in _CLOSERS:
            j += 1
        if ch == "." and j == i + 1:
            m = _WORD_BEFORE.search(text[:i])
            word = m.group(1) if m else ""
            if len(word) == 1 or word.lower() in _ABBREVIATIONS:
                i = j
                continue
        if j >= n:
            ends.append(n)
        elif text[j].isspace():
            k = j
            while k < n and text[k].isspace():
                k += 1
            if k >= n:
                ends.append(n)
            elif not text[k].islower():
                ends.append(j)
        i = j
    return ends


def bio_excerpt(text: Optional[str], limit: int = DEFAULT_LIMIT) -> Optional[str]:
    """The first one or two sentences of `text` within `limit` characters, or
    None when there is no text."""
    if not text:
        return None
    # First paragraph only, whitespace collapsed.
    first = next((p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()), "")
    flat = " ".join(first.split())
    if not flat:
        return None
    ends = _sentence_ends(flat)
    cut = 0
    for end in ends[:MAX_SENTENCES]:
        if end <= limit:
            cut = end
    if cut:
        return flat[:cut].rstrip()
    if len(flat) <= limit:
        return flat
    room = flat[: limit - 1]
    space = room.rfind(" ")
    if space > 0:
        room = room[:space]
    return room.rstrip(" ,;:-") + "…"
