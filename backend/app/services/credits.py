"""Artist credit parsing and merge-alias resolution.

Two concerns live here so the folder scan (scan_library.py) and the Lidarr
sync (sync.py) share one implementation:

1. Scan-time credit normalization. A track credited "2Pac Featuring KC and
   JoJo" should land under the main artist ("2Pac") while the full credit text
   is kept for display on the album and track. A "Featuring", "feat." or "ft."
   credit is split to its main artist automatically. "&" and "And" are never
   auto-split, so "Simon & Garfunkel" and "Earth, Wind & And" stay one artist
   (the UI suggests those as a merge instead).

2. Merge-alias resolution. After an admin merges one artist into another, a
   saved alias (artist_aliases) maps the source name and MusicBrainz id to the
   target. Both scanners resolve an incoming name and MBID through the alias
   before they create or look up an Artist row, so a rescan or a sync does not
   recreate the merged-away source artist.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.music import Artist, ArtistAlias


# The "featuring" join only. Case-insensitive, with optional surrounding
# whitespace / punctuation. "feat" and "ft" accept a trailing dot. These are
# the only joins that auto-split; "&" and "and" are deliberately absent.
_FEAT_RE = re.compile(
    r"\s*(?:\(|\[)?\s*"
    r"(?:feat\.?|ft\.?|featuring|with)\b"
    r"[\s.:]*",
    re.IGNORECASE,
)


@dataclass
class ParsedCredit:
    """The result of reading an artist credit.

    `main` is the artist the record should file under. `credited_as` is the
    full original credit text when it named more than the main artist (so the
    album / track can still show "2Pac featuring KC and JoJo"), else None.
    """

    main: str
    credited_as: Optional[str]


def parse_credit(raw: Optional[str]) -> ParsedCredit:
    """Split a "featuring" credit to its main artist, keeping the full text.

    "2Pac Featuring KC And Jojo" -> main "2Pac", credited_as the full string.
    "Simon & Garfunkel"          -> main "Simon & Garfunkel", credited_as None
    (an "&" credit is never auto-split).
    """
    text = (raw or "").strip()
    if not text:
        return ParsedCredit(main="", credited_as=None)
    m = _FEAT_RE.search(text)
    if not m or m.start() == 0:
        return ParsedCredit(main=text, credited_as=None)
    main = text[: m.start()].strip(" -_.([")
    if not main:
        return ParsedCredit(main=text, credited_as=None)
    return ParsedCredit(main=main, credited_as=text)


def resolve_artist(
    db: Session, *, name: str, mbid: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[Artist]]:
    """Route an incoming artist credit through the merge aliases.

    Returns `(name, mbid, target)` where `target` is the Artist a saved alias
    points at (else None) and `name` / `mbid` are rewritten to the target's own
    name and mbid when an alias matched. Match order is MBID first (the strong
    key), then the lowercased name. The caller still does its own name / MBID
    Artist lookup; this only redirects a merged-away source to its target so a
    rescan does not recreate it.
    """
    alias = None
    if mbid:
        alias = db.scalar(
            select(ArtistAlias).where(ArtistAlias.source_mbid == mbid)
        )
    if alias is None and name:
        alias = db.scalar(
            select(ArtistAlias).where(ArtistAlias.name_key == name.lower())
        )
    if alias is None:
        return name, mbid, None
    target = db.get(Artist, alias.target_artist_id)
    if target is None:
        # Dangling alias (target removed out from under it). Fall back to the
        # incoming credit so the scan still files the track somewhere.
        return name, mbid, None
    return target.name, target.mbid, target
