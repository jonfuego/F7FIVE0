"""iTunes Search API adapter.

Used as a fallback artist art source when Lidarr returns nothing useful.
The legacy Search API is the only Apple endpoint that works without
authentication; it does not return artist portraits directly, but album
artwork keyed to the artist is high-quality and a reasonable proxy for
an artist thumbnail in the modal.

Strategy:
1. Hit `lookup?term=<name>&entity=musicArtist&limit=1` to find the
   canonical Apple artistId. This avoids picking up tribute bands,
   karaoke covers, and same-named soundtracks that show up when the
   query goes straight to the album endpoint.
2. If a matching artist is found, fetch their albums via
   `lookup?id=<artistId>&entity=album&limit=12`. Each album has an
   `artworkUrl100`; the URL pattern lets us swap `100x100bb.jpg` for
   `1000x1000bb.jpg` for a usable resolution.
3. Fall back to a direct `search?term=<name>&entity=album&attribute=
   artistTerm&limit=12` if the artist lookup misses, and filter the
   results to entries whose `artistName` matches (case-insensitive).

No API key, no signup. Apple rate-limits anonymous traffic but the
modal makes at most one search per modal-open so we stay well under.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any, Optional

import httpx

from app.services.art_sources import previews


_BASE = "https://itunes.apple.com"
_TIMEOUT = 6.0
_log = logging.getLogger("f7five0.art_sources.itunes")


def search_artist(name: str) -> list[dict[str, Any]]:
    """Return a candidate list for the given artist name. `[]` on failure."""
    if not name or not name.strip():
        return []
    name = name.strip()
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"}) as client:
            artist_id = _lookup_artist_id(client, name)
            albums = _lookup_albums(client, artist_id) if artist_id else []
            if not albums:
                albums = _search_albums(client, name)
    except httpx.HTTPError as exc:
        _log.warning("iTunes lookup failed for %r: %s", name, exc)
        return []

    return _normalize_albums(albums, expected_artist=name)


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------
def _lookup_artist_id(client: httpx.Client, name: str) -> Optional[int]:
    resp = client.get(
        f"{_BASE}/search",
        params={"term": name, "entity": "musicArtist", "limit": 1},
    )
    if resp.status_code != 200:
        return None
    body = _safe_json(resp)
    results = (body or {}).get("results") or []
    if not results:
        return None
    first = results[0] or {}
    if not _name_matches(first.get("artistName"), name):
        return None
    aid = first.get("artistId")
    return int(aid) if isinstance(aid, int) else None


def _lookup_albums(client: httpx.Client, artist_id: int) -> list[dict[str, Any]]:
    resp = client.get(
        f"{_BASE}/lookup",
        params={"id": artist_id, "entity": "album", "limit": 12},
    )
    if resp.status_code != 200:
        return []
    body = _safe_json(resp)
    results = (body or {}).get("results") or []
    # The first result is the artist record itself; albums follow.
    return [r for r in results if (r or {}).get("wrapperType") == "collection"]


def _search_albums(client: httpx.Client, name: str) -> list[dict[str, Any]]:
    resp = client.get(
        f"{_BASE}/search",
        params={
            "term": name,
            "entity": "album",
            "attribute": "artistTerm",
            "limit": 12,
        },
    )
    if resp.status_code != 200:
        return []
    body = _safe_json(resp)
    results = (body or {}).get("results") or []
    return [
        r for r in results
        if (r or {}).get("wrapperType") == "collection"
        and _name_matches((r or {}).get("artistName"), name)
    ]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _normalize_albums(
    albums: list[dict[str, Any]], *, expected_artist: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for album in albums:
        if not isinstance(album, dict):
            continue
        art = album.get("artworkUrl100") or album.get("artworkUrl60")
        if not isinstance(art, str) or not art.startswith("https://"):
            continue
        # Apple's CDN exposes higher-resolution variants by swapping the
        # size segment in the path. 1000x1000 is the practical upper bound
        # we'll get for older catalog entries; newer ones go higher but
        # this size is reliable everywhere.
        hi = _upscale(art)
        if hi in seen_urls:
            continue
        seen_urls.add(hi)
        title = album.get("collectionName") or "album"
        out.append({
            "source": "itunes",
            "ref": hi,
            "url": hi,
            # The tile loads a 300 px copy; applying downloads `url`.
            "preview_url": previews.itunes_url(hi, previews.ITUNES_PREVIEW_SIZE),
            "label": f"iTunes album: {title}",
        })
    return out


def _upscale(url: str) -> str:
    """Rewrite Apple's `/100x100bb.jpg` segment to `/1000x1000bb.jpg`.

    The CDN accepts any `<w>x<h>bb.<ext>` pattern; if the original
    doesn't match we leave it alone and the modal shows the smaller
    image rather than a broken one.
    """
    for size in ("100x100bb", "60x60bb", "300x300bb", "600x600bb"):
        if size in url:
            return url.replace(size, "1000x1000bb")
    return url


def _name_matches(candidate: Optional[str], expected: str) -> bool:
    """Loose case/whitespace match. Apple normalizes punctuation oddly
    (e.g. `AC/DC` returns as `AC/DC`, but `Beyoncé` may return without
    the accent), so this is intentionally permissive."""
    if not isinstance(candidate, str):
        return False
    return _norm(candidate) == _norm(expected)


def _norm(s: str) -> str:
    """Whitespace-collapse, casefold, and strip combining marks.

    NFKD + dropping combining-mark codepoints lets `Beyoncé` and
    `Beyonce` compare equal — Apple's catalog is inconsistent about
    diacritics and we'd rather have a loose match than miss the artist.
    """
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.split()).casefold()


def _safe_json(resp: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return resp.json()
    except ValueError:
        return None
