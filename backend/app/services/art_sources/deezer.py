"""Deezer artist pictures: the keyless artist image source.

    GET https://api.deezer.com/search/artist?q=<name>&limit=10

needs no key and no signup, and returns ready-made square artist photos at
four sizes (`picture_small` 56 px, `picture_medium` 250 px, `picture_big`
500 px, `picture_xl` 1000 px). The tile loads `picture_medium`; applying
downloads `picture_xl`.

Match quality is the hard part: a search for "New Order" also returns
"The New Order" and "New Beat Order", and the same name can exist twice (one
with 949 thousand fans, one with 94). So a result is
accepted only when its name equals the library name after `names.match_key`
folding (a leading "the" is ignored only when no artist matches without
that), it has a real picture (an artist with none gets a placeholder URL
with an empty hash segment, `/images/artist//1000x1000-...`), and the most
followed match comes first.

Failures raise `DeezerError` (HTTP error, transport error, or Deezer's
`{"error": {...}}` body, which it sends with a 200 when over quota) so the
art modal can say "Deezer did not answer" instead of showing nothing. A search
with no match returns `[]`.

Terms: the API is free and unauthenticated for this kind of lookup. Deezer
owns the pictures; the server keeps a private copy for the owner's own library
tiles (art is never served publicly), the same way it keeps iTunes and TMDB
images.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.services.art_sources import names


_BASE = "https://api.deezer.com"
_TIMEOUT = 6.0
_LIMIT = 10
# Most matches the modal shows. Two real artists can share a name; more than a
# few is noise.
_MAX_CANDIDATES = 3
_log = logging.getLogger("f7five0.art_sources.deezer")


class DeezerError(Exception):
    """Deezer could not answer (HTTP, transport, or quota error)."""


def search_artist(name: str) -> list[dict[str, Any]]:
    """Candidates for the art modal: up to three same-name artists, most
    followed first. `[]` when nothing matches. Raises `DeezerError` when Deezer
    cannot answer."""
    out: list[dict[str, Any]] = []
    for i, hit in enumerate(_matches(name)[:_MAX_CANDIDATES]):
        url = hit["picture_xl"]
        out.append({
            "source": "deezer",
            "ref": url,
            "url": url,
            "preview_url": hit.get("picture_medium") or url,
            "label": "Deezer artist photo" if i == 0 else f"Deezer artist photo {i + 1}",
        })
    return out


def best_picture(name: str) -> Optional[str]:
    """The full-size picture URL of the best same-name artist, or None. Used by
    the auto-fill job. Raises `DeezerError` when Deezer cannot answer."""
    hits = _matches(name)
    return hits[0]["picture_xl"] if hits else None


def _matches(name: str) -> list[dict[str, Any]]:
    if not name or not name.strip():
        return []
    name = name.strip()
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"}) as client:
            resp = client.get(
                f"{_BASE}/search/artist", params={"q": name, "limit": _LIMIT},
            )
    except httpx.HTTPError as exc:
        _log.warning("Deezer search for %r failed: %s", name, exc)
        raise DeezerError(f"transport error: {exc}") from exc
    if resp.status_code != 200:
        _log.info("Deezer returned %s for %r", resp.status_code, name)
        raise DeezerError(f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise DeezerError("answer was not JSON") from exc
    if not isinstance(body, dict) or body.get("error"):
        raise DeezerError("Deezer returned an error (quota or bad request)")
    data = body.get("data")
    if not isinstance(data, list):
        return []
    usable = [a for a in data if isinstance(a, dict) and _has_picture(a)]
    # Exact name first. A leading "the" is ignored only when no artist matches
    # without that leniency ("The New Order" must not stand in for "New
    # Order" when the real one is there).
    for drop_the in (False, True):
        hits = [
            a for a in usable
            if names.same_artist(str(a.get("name") or ""), name, drop_the=drop_the)
        ]
        if hits:
            hits.sort(key=lambda a: _fans(a), reverse=True)
            return hits
    return []


def _fans(artist: dict[str, Any]) -> int:
    n = artist.get("nb_fan")
    return n if isinstance(n, int) else 0


def _has_picture(artist: dict[str, Any]) -> bool:
    """A real picture URL, not the placeholder (`.../artist//1000x1000-...`)
    Deezer returns for an artist with no photo."""
    url = artist.get("picture_xl")
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    return "/artist//" not in url
