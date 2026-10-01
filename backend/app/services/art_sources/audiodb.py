"""TheAudioDB adapter for artist artwork.

Returns the actual artist portraits and fanart that iTunes does not
expose — strArtistThumb, strArtistFanart{,2,3,4}, strArtistBanner,
strArtistLogo, strArtistClearart, strArtistCutout, strArtistWideThumb.
Coverage is good for any artist with a Wikipedia or AllMusic presence.

API:
    GET https://www.theaudiodb.com/api/v1/json/<key>/search.php?s=<name>
returns:
    {"artists": [{...}]} on hit, {"artists": null} on miss.

The public test key "2" works for one-user personal traffic. Replace
with a Patreon-supporter key in settings if rate-limited.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any, Optional

import httpx


_BASE = "https://www.theaudiodb.com/api/v1/json"
_TIMEOUT = 6.0
_log = logging.getLogger("f7five0.art_sources.audiodb")

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


def search_artist(api_key: str, name: str) -> list[dict[str, Any]]:
    """Return TheAudioDB artwork for the given artist name.

    Empty list on missing key, missing name, transport error, or no
    matching artist. Hard failures never propagate; this is a best-
    effort fallback the aggregator will silently skip.
    """
    if not api_key or not name or not name.strip():
        return []
    name = name.strip()
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"}) as client:
            resp = client.get(
                f"{_BASE}/{api_key}/search.php",
                params={"s": name},
            )
    except httpx.HTTPError as exc:
        _log.warning("TheAudioDB search for %r failed: %s", name, exc)
        return []
    if resp.status_code != 200:
        _log.info("TheAudioDB returned %s for %r", resp.status_code, name)
        return []
    body = _safe_json(resp) or {}
    artists = body.get("artists") or []
    if not isinstance(artists, list) or not artists:
        return []
    # Prefer an exact (accent-insensitive) name match; fall back to the
    # first result so we still surface art for slight spelling variants.
    chosen = _pick_match(artists, name) or artists[0]
    if not isinstance(chosen, dict):
        return []
    return _normalize(chosen)


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
            "label": f"AudioDB {label_suffix}",
        })
    return out


def _pick_match(
    artists: list[Any], expected: str,
) -> Optional[dict[str, Any]]:
    target = _norm(expected)
    for a in artists:
        if isinstance(a, dict) and _norm(str(a.get("strArtist") or "")) == target:
            return a
    return None


def _norm(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.split()).casefold()


def _safe_json(resp: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return resp.json()
    except ValueError:
        return None
