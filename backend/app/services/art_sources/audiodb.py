"""TheAudioDB adapter for artist artwork.

Returns the actual artist portraits and fanart that iTunes does not
expose — strArtistThumb, strArtistFanart{,2,3,4}, strArtistBanner,
strArtistLogo, strArtistClearart, strArtistCutout, strArtistWideThumb.
Coverage is good for any artist with a Wikipedia or AllMusic presence.

API (v1, https):
    GET https://www.theaudiodb.com/api/v1/json/<key>/search.php?s=<name>
    GET https://www.theaudiodb.com/api/v1/json/<key>/artist-mb.php?i=<mbid>
return {"artists": [{...}]} on a hit and {"artists": null} (HTTP 200) on a
miss. Images now live on r2.theaudiodb.com.

The free public key is "123". The old test key "2" is retired: TheAudioDB
answers it with HTTP 404 `{"Message": "Not found"}` for every request, which
this adapter used to treat as "no artist" and return `[]`, so artist art search
showed no AudioDB candidates at all. `effective_key` maps "1" and "2" (still
in many `.env` files, copied from the old `.env.example`) to "123". Any other
HTTP failure now raises `AudioDBError`, so the modal says "TheAudioDB did not
answer" instead of silently showing nothing. A Patreon-supporter key in
settings lifts the free key's rate limit.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.services.art_sources import names, previews


_BASE = "https://www.theaudiodb.com/api/v1/json"
_TIMEOUT = 6.0
_log = logging.getLogger("f7five0.art_sources.audiodb")

FREE_KEY = "123"
# Retired public test keys. TheAudioDB 404s every request made with them.
_RETIRED_KEYS = frozenset({"1", "2"})


class AudioDBError(Exception):
    """TheAudioDB could not answer (HTTP error, transport error, bad body)."""


def effective_key(api_key: Optional[str]) -> str:
    """The key to send: the saved one, with a retired test key replaced by
    the current free key. Blank stays blank (the source is off)."""
    key = (api_key or "").strip()
    return FREE_KEY if key in _RETIRED_KEYS else key

# (field name on the artist dict, human-readable label suffix). Order
# matters: it's how candidates surface in the modal. Lead with thumb
# because that's the closest analogue to the per-artist "thumb" role we
# pin overrides under.
_FIELDS: tuple[tuple[str, str], ...] = (
    ("strArtistThumb", "thumb"),
    ("strArtistFanart", "fanart"),
    ("strArtistFanart2", "fanart 2"),
    ("strArtistFanart3", "fanart 3"),
    ("strArtistFanart4", "fanart 4"),
    ("strArtistBanner", "banner"),
    ("strArtistWideThumb", "wide thumb"),
    ("strArtistLogo", "logo"),
    ("strArtistClearart", "clearart"),
    ("strArtistCutout", "cutout"),
)


def search_artist(
    api_key: str, name: str, mbid: Optional[str] = None, *, strict: bool = False,
) -> list[dict[str, Any]]:
    """Return TheAudioDB artwork for the given artist.

    With an `mbid` the artist is looked up by MusicBrainz id first (an exact
    match, no guessing); without one, or when that finds nothing, by name.
    By name, an exact (accent-insensitive) match wins and the first result is
    the fallback so slight spelling variants still surface art in the modal;
    `strict` drops that fallback (the auto-fill job uses it, because it saves
    the picture without an admin looking).

    `[]` on a missing key or name or no matching artist. Raises
    `AudioDBError` when TheAudioDB cannot answer, so the caller can say so.
    """
    api_key = effective_key(api_key)
    if not api_key or not name or not name.strip():
        return []
    name = name.strip()
    chosen: Optional[dict[str, Any]] = None
    if mbid and mbid.strip():
        found = _artists(api_key, "artist-mb.php", {"i": mbid.strip()})
        chosen = found[0] if found and isinstance(found[0], dict) else None
    if chosen is None:
        found = _artists(api_key, "search.php", {"s": name})
        chosen = _pick_match(found, name)
        if chosen is None and not strict and found and isinstance(found[0], dict):
            chosen = found[0]
    if chosen is None:
        return []
    return _normalize(chosen)


def thumb_url(api_key: str, name: str, mbid: Optional[str] = None) -> Optional[str]:
    """The artist's portrait (`strArtistThumb`) for an exact name or MBID
    match, or None. Used by the auto-fill job. Raises `AudioDBError`."""
    for item in search_artist(api_key, name, mbid, strict=True):
        if item["label"] == "AudioDB thumb":
            return item["url"]
    return None


def _artists(api_key: str, endpoint: str, params: dict[str, str]) -> list[Any]:
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"}) as client:
            resp = client.get(f"{_BASE}/{api_key}/{endpoint}", params=params)
    except httpx.HTTPError as exc:
        _log.warning("TheAudioDB %s failed: %s", endpoint, exc)
        raise AudioDBError(f"transport error: {exc}") from exc
    if resp.status_code != 200:
        _log.warning("TheAudioDB %s returned HTTP %s", endpoint, resp.status_code)
        raise AudioDBError(f"HTTP {resp.status_code}")
    body = _safe_json(resp)
    if body is None:
        raise AudioDBError("answer was not JSON")
    artists = body.get("artists")
    return artists if isinstance(artists, list) else []


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _normalize(artist: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field, label_suffix in _FIELDS:
        url = artist.get(field)
        if not isinstance(url, str) or not url.startswith("https://"):
            # AudioDB occasionally returns http:// — promote to https
            # because the modal renders these in a CSP-restricted page.
            if isinstance(url, str) and url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            else:
                continue
        if url in seen:
            continue
        seen.add(url)
        out.append({
            "source": "audiodb",
            "ref": url,
            "url": url,
            # `<image>.jpg/small` is a 250 px copy; applying downloads `url`.
            "preview_url": previews.audiodb_url(url, previews.AUDIODB_PREVIEW_VARIANT),
            "label": f"AudioDB {label_suffix}",
        })
    return out


def _pick_match(
    artists: list[Any], expected: str,
) -> Optional[dict[str, Any]]:
    for a in artists:
        if isinstance(a, dict) and names.same_artist(str(a.get("strArtist") or ""), expected):
            return a
    return None


def _safe_json(resp: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None
