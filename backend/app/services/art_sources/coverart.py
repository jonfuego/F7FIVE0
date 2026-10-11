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
        url, preview = _urls(img)
        if not url or url in seen:
            continue
        seen.add(url)
        label = "Cover Art front" if img.get("front") else "Cover Art"
        item: dict[str, Any] = {
            "source": "coverart",
            "ref": url,
            "url": url,
            "label": label,
        }
        if preview:
            item["preview_url"] = preview
        out.append(item)
    return out[:24]


def _urls(img: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Return `(apply_url, preview_url)` for one Cover Art Archive image.

    The tile loads the 250 px thumbnail (falling back to 500 px). Applying
    downloads the 1200 px thumbnail rather than the raw upload: originals are
    often tens of MB, past the 10 MB cap in `fetch_and_save_url`, so a pick
    would fail with a 413. Without a 1200 px thumbnail it falls back to the
    500 px one, then the original.
    """
    thumbs = img.get("thumbnails") or {}
    if not isinstance(thumbs, dict):
        thumbs = {}

    def pick(*sizes: str) -> Optional[str]:
        for size in sizes:
            candidate = thumbs.get(size)
            if isinstance(candidate, str) and candidate.startswith("https://"):
                return candidate
        return None

    full = img.get("image")
    original = full if isinstance(full, str) and full.startswith("https://") else None
    apply_url = pick("1200", "500", "large") or original
    preview = pick("250", "small", "500", "large")
    return apply_url, preview


def _safe_json(resp: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return resp.json()
    except ValueError:
        return None
