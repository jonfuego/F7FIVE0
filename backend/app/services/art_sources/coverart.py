"""Cover Art Archive adapter for album artwork.

The Cover Art Archive serves cover images keyed by a MusicBrainz release-
group MBID. No key, no signup. The JSON endpoint lists the images for a
release-group and marks which one is the front cover.

API:
    GET https://coverartarchive.org/release-group/<mbid>
returns:
    {"images": [{"image": "https://...", "front": true,
                 "thumbnails": {"500": "https://...", ...}}, ...]}
    404 when the release-group has no cover art.

Best-effort: any missing MBID, transport error, 404, or parse failure
returns `[]` so the aggregator silently skips this source.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx


_BASE = "https://coverartarchive.org"
_TIMEOUT = 6.0
_log = logging.getLogger("f7five0.art_sources.coverart")


def release_group_images(mbid: Optional[str]) -> list[dict[str, Any]]:
    """Return Cover Art Archive candidates for a release-group MBID.

    `[]` on missing MBID, transport error, 404, or no images.
    """
    if not mbid or not str(mbid).strip():
        return []
    mbid = str(mbid).strip()
    try:
        with httpx.Client(
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            resp = client.get(f"{_BASE}/release-group/{mbid}")
    except httpx.HTTPError as exc:
        _log.warning("Cover Art Archive lookup for %s failed: %s", mbid, exc)
        return []
    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        _log.info("Cover Art Archive returned %s for %s", resp.status_code, mbid)
        return []
    body = _safe_json(resp) or {}
    images = body.get("images") or []
    if not isinstance(images, list):
        return []
    return _normalize(images)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _normalize(images: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Front covers first so the most useful art sorts to the top.
    ordered = sorted(
        (i for i in images if isinstance(i, dict)),
        key=lambda i: 0 if i.get("front") else 1,
    )
    for img in ordered:
        url = _best_url(img)
        if not url or url in seen:
            continue
        seen.add(url)
        label = "Cover Art front" if img.get("front") else "Cover Art"
        out.append({
            "source": "coverart",
            "ref": url,
            "url": url,
            "label": label,
        })
    return out[:24]


def _best_url(img: dict[str, Any]) -> Optional[str]:
    """Prefer a 500px thumbnail over the full-size original.

    Full originals can be many megabytes; the modal renders a thumbnail
    grid, so the 500px variant is both lighter and still sharp enough. We
    fall back to the full image when no thumbnail is listed.
    """
    thumbs = img.get("thumbnails") or {}
    if isinstance(thumbs, dict):
        for size in ("500", "large", "250"):
            candidate = thumbs.get(size)
            if isinstance(candidate, str) and candidate.startswith("https://"):
                return candidate
    full = img.get("image")
    if isinstance(full, str) and full.startswith("https://"):
        return full
    return None


def _safe_json(resp: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return resp.json()
    except ValueError:
        return None
