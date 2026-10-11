"""TMDB v3 API adapter for movie and series art.

Used as a fallback when Radarr/Sonarr return nothing useful. TMDB is
the source most *arr installations pull from internally, so this
provides a clean way to recover art for entities whose *arr metadata
hasn't been refreshed.

Takes the key from the caller (app/services/tmdb_key.py). Empty key => `[]` everywhere
(callers see the source as silently unconfigured, the same way
Lidarr-without-a-key already behaves).

API shape:
    GET /3/movie/{id}/images?api_key=...
    GET /3/tv/{id}/images?api_key=...
returns:
    {
      "id": <int>,
      "backdrops": [{"file_path": "/abc.jpg", "iso_639_1": "en", ...}, ...],
      "posters":   [{"file_path": "/def.jpg", "iso_639_1": "en", ...}, ...],
      "logos":     [...]   # tv only
    }

We resolve `file_path` against TMDB's image base. Applying downloads the
original-quality URL, `https://image.tmdb.org/t/p/original{file_path}` (`url`).
The modal's tile loads a small variant instead (`preview_url`, `w342` for
posters, `w300` for backdrops); an `original` poster is several MB, which is
too much for a 24-tile grid. Posters are 2:3, backdrops are 16:9; both are
returned because the modal can be opened with `role=poster` or `role=backdrop`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.services.art_sources import previews


_BASE = "https://api.themoviedb.org/3"
_IMG_SIZE_FULL = "original"
_TIMEOUT = 6.0
_log = logging.getLogger("f7five0.art_sources.tmdb")


def movie_images(api_key: str, tmdb_id: int) -> list[dict[str, Any]]:
    """Return TMDB poster + backdrop candidates for a movie. `[]` on failure."""
    return _fetch_images(api_key, kind="movie", tmdb_id=tmdb_id)


def series_images(api_key: str, tmdb_id: int) -> list[dict[str, Any]]:
    """Return TMDB poster + backdrop candidates for a series. `[]` on failure.

    TMDB's TV endpoint is `/tv/{id}` not `/series/{id}`. The wrapper here
    keeps the kind word aligned with our schema names so callers don't
    have to remember the mismatch.
    """
    return _fetch_images(api_key, kind="tv", tmdb_id=tmdb_id)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------
def _fetch_images(
    api_key: str, *, kind: str, tmdb_id: Optional[int],
) -> list[dict[str, Any]]:
    if not api_key or not tmdb_id:
        return []
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"Accept": "application/json"}) as client:
            resp = client.get(
                f"{_BASE}/{kind}/{tmdb_id}/images",
                params={"api_key": api_key, "include_image_language": "en,null"},
            )
    except httpx.HTTPError as exc:
        _log.warning("TMDB %s/%s images failed: %s", kind, tmdb_id, exc)
        return []
    if resp.status_code != 200:
        _log.info("TMDB %s/%s images returned %s", kind, tmdb_id, resp.status_code)
        return []
    body = _safe_json(resp) or {}
    posters = body.get("posters") or []
    backdrops = body.get("backdrops") or []

    out: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    # Posters first so they sort to the top of the modal grid; the modal
    # is more often opened on `role=poster` than `role=backdrop`.
    for entry in posters:
        item = _normalize(entry, label_kind="poster")
        if item and item["ref"] not in seen_paths:
            seen_paths.add(item["ref"])
            out.append(item)
    for entry in backdrops:
        item = _normalize(entry, label_kind="backdrop")
        if item and item["ref"] not in seen_paths:
            seen_paths.add(item["ref"])
            out.append(item)
    # Cap at 24 so the grid stays scannable even for blockbusters with
    # 50+ posters across language editions.
    return out[:24]


def _normalize(
    entry: dict[str, Any], *, label_kind: str,
) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    path = entry.get("file_path")
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    lang = entry.get("iso_639_1")
    lang_tag = f" [{lang}]" if isinstance(lang, str) and lang and lang != "en" else ""
    preview_size = (
        previews.TMDB_BACKDROP_PREVIEW if label_kind == "backdrop"
        else previews.TMDB_POSTER_PREVIEW
    )
    return {
        "source": "tmdb",
        "ref": path,
        "url": previews.tmdb_url(path, _IMG_SIZE_FULL),
        "preview_url": previews.tmdb_url(path, preview_size),
        "label": f"TMDB {label_kind}{lang_tag}",
    }


def _safe_json(resp: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return resp.json()
    except ValueError:
        return None
