"""Aggregate candidate art from the *arr stack.

For a given (kind, entity_id) pair, this asks the appropriate *arr which
images it knows about for the entity, normalizes them into a flat list of
`{source, ref, url, label}` dicts, and returns it. The frontend renders
each candidate as a tile in the modal's Search tab; the admin clicks one
and the backend downloads it through the existing `fetch_and_save_url`.

Each *arr exposes an `images` array on its detail endpoint with entries
shaped like `{coverType, url, remoteUrl}`. We prefer `remoteUrl` because
that is what the local *arr proxy resolves to a public CDN. Entries
without a `remoteUrl` are skipped (Lidarr's `disc` covers in particular
sometimes lack one).

When the local entity has no upstream id (music-videos-only artists, for
instance), we fall back to the `*/lookup` endpoints with the entity's
title as the search term. The first result's images become the candidate
list. Lookup is best-effort: a missing match returns an empty list, not
an error, so the modal can show a clean "No candidates" state.

`ArrClientError` propagates so the caller (the API layer) can degrade to
[] when an *arr is unconfigured or down rather than 500'ing the modal.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.art import (
    ENTITY_ARTIST, ENTITY_MOVIE, ENTITY_MUSIC_VIDEO, ENTITY_SERIES,
)
from app.models.movie import Movie
from app.models.music import Artist, MusicVideo
from app.models.tv import Series
from app.services import tmdb_key
from app.services.arr import LidarrClient, RadarrClient, SonarrClient
from app.services.arr._base import ArrClientError
from app.services.art_sources import audiodb as audiodb_source
from app.services.art_sources import itunes as itunes_source
from app.services.art_sources import tmdb as tmdb_source


log = logging.getLogger("f7five0.art_search")


def search_candidates(
    db: Session,
    *,
    kind: str,
    entity_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return a flat list of candidate art for the entity.

    Each entry: `{source, ref, url, label}`. `source` is the provider
    name (`lidarr` / `radarr` / `sonarr`). `ref` is the candidate's
    upstream identifier (the `remoteUrl` itself today). `url` is the
    resolvable image URL. `label` is the display string the modal puts
    under the thumbnail.

    Empty list when the relevant *arr is unconfigured or returns nothing
    useful. Raises `ArrClientError` only on hard failures the API layer
    will catch and convert to [].
    """
    if kind == ENTITY_ARTIST:
        return _artist_candidates(db, entity_id)
    if kind == ENTITY_MOVIE:
        return _movie_candidates(db, entity_id)
    if kind == ENTITY_SERIES:
        return _series_candidates(db, entity_id)
    if kind == ENTITY_MUSIC_VIDEO:
        return _music_video_candidates(db, entity_id)
    return []


# ---------------------------------------------------------------------------
# Per-kind aggregators
# ---------------------------------------------------------------------------
def _artist_candidates(
    db: Session, entity_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Artist art: real portraits and fanart only.

    Lidarr's get_artist returns artist-level images (poster/fanart/
    banner/logo) which are genuine artist artwork. AudioDB likewise
    returns artist portraits. iTunes is intentionally skipped here
    because the unauthenticated Search API only surfaces album covers,
    and album art doesn't belong on the artist tile. The music-video
    aggregator still uses iTunes since album art is a defensible thumb
    for a video.
    """
    artist = db.get(Artist, entity_id)
    if artist is None:
        return []
    out = _lidarr_artist_images(artist.lidarr_id, artist.name)
    out.extend(_audiodb_artist_images(artist.name))
    return _dedupe_by_url(out)


def _movie_candidates(
    db: Session, entity_id: uuid.UUID,
) -> list[dict[str, Any]]:
    movie = db.get(Movie, entity_id)
    if movie is None:
        return []
    out: list[dict[str, Any]] = []
    client = _radarr()
    if client.configured:
        images: list[dict[str, Any]] = []
        try:
            if movie.radarr_id is not None:
                payload = client.get_movie(movie.radarr_id)
                images = list(payload.get("images") or [])
            if not images and movie.title:
                results = client.movie_lookup(movie.title)
                chosen = _pick_lookup_match(
                    results, imdb_id=movie.imdb_id, tmdb_id=movie.tmdb_id,
                )
                if chosen is not None:
                    images = list(chosen.get("images") or [])
        finally:
            client.close()
        out.extend(_normalize_images("radarr", "Radarr", images))
    if movie.tmdb_id and tmdb_key.get():
        out.extend(tmdb_source.movie_images(tmdb_key.get(), movie.tmdb_id))
    return _dedupe_by_url(out)


def _series_candidates(
    db: Session, entity_id: uuid.UUID,
) -> list[dict[str, Any]]:
    series = db.get(Series, entity_id)
    if series is None:
        return []
    out: list[dict[str, Any]] = []
    client = _sonarr()
    if client.configured:
        images: list[dict[str, Any]] = []
        try:
            if series.sonarr_id is not None:
                payload = client.get_series(series.sonarr_id)
                images = list(payload.get("images") or [])
            if not images and series.title:
                results = client.series_lookup(series.title)
                chosen = _pick_lookup_match(
                    results, tvdb_id=series.tvdb_id, tmdb_id=series.tmdb_id,
                )
                if chosen is not None:
                    images = list(chosen.get("images") or [])
        finally:
            client.close()
        out.extend(_normalize_images("sonarr", "Sonarr", images))
    if series.tmdb_id and tmdb_key.get():
        out.extend(tmdb_source.series_images(tmdb_key.get(), series.tmdb_id))
    return _dedupe_by_url(out)


def _music_video_candidates(
    db: Session, entity_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Music videos do not have their own *arr representation. Surface
    the parent artist's Lidarr / AudioDB / iTunes images so the admin
    can pick a relevant portrait, fanart, or album cover as the per-
    video thumb."""
    mv = db.get(MusicVideo, entity_id)
    if mv is None:
        return []
    artist = db.get(Artist, mv.artist_id)
    if artist is None:
        return []
    out = _lidarr_artist_images(artist.lidarr_id, artist.name)
    out.extend(_audiodb_artist_images(artist.name))
    out.extend(_itunes_artist_images(artist.name))
    return _dedupe_by_url(out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _itunes_artist_images(name: Optional[str]) -> list[dict[str, Any]]:
    """Best-effort iTunes album-art fallback for an artist."""
    if not settings.itunes_enabled or not name:
        return []
    return itunes_source.search_artist(name)


def _audiodb_artist_images(name: Optional[str]) -> list[dict[str, Any]]:
    """TheAudioDB portraits/fanart fallback for an artist."""
    if not settings.audiodb_api_key or not name:
        return []
    return audiodb_source.search_artist(settings.audiodb_api_key, name)


def _dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable dedupe across sources. First occurrence wins so Lidarr/Radarr
    sit above iTunes/TMDB when both return the same upstream URL (rare in
    practice but worth handling)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def _lidarr_artist_images(
    lidarr_id: Optional[int], name: Optional[str],
) -> list[dict[str, Any]]:
    client = _lidarr()
    if not client.configured:
        return []
    images: list[dict[str, Any]] = []
    try:
        if lidarr_id is not None:
            payload = client.get_artist(lidarr_id)
            images = list(payload.get("images") or [])
        if not images and name:
            results = client.artist_lookup(name)
            if results:
                images = list((results[0] or {}).get("images") or [])
    finally:
        client.close()
    return _normalize_images("lidarr", "Lidarr", images)


def _normalize_images(
    source: str, label_prefix: str, images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map *arr `images` entries to the modal's wire shape and dedupe.

    *arr returns entries like `{coverType: "poster", url: "/...", remoteUrl: "https://..."}`.
    We rely on `remoteUrl` because the local `/MediaCover/...` urls aren't
    reachable from the browser. Entries without one are dropped. Cover
    type drives the label; the ref is the remoteUrl so the from-search
    endpoint can re-derive it without the modal echoing a full URL back.
    """
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for img in images:
        if not isinstance(img, dict):
            continue
        url = img.get("remoteUrl")
        if not isinstance(url, str) or not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        cover_type = img.get("coverType") or "image"
        out.append({
            "source": source,
            "ref": url,
            "url": url,
            "label": f"{label_prefix} {cover_type}",
        })
    return out


def _pick_lookup_match(
    results: list[dict[str, Any]], **keys: Any,
) -> Optional[dict[str, Any]]:
    """Pick the lookup result whose external IDs match the local entity.

    Falls through to the first result if no key matches; *arr's lookup
    returns the closest match first. We never invent a match; the caller
    handles the empty case by returning an empty candidate list.
    """
    if not results:
        return None
    for r in results:
        for k, v in keys.items():
            if v is None:
                continue
            if r.get(k) == v:
                return r
    return results[0]


def _lidarr() -> LidarrClient:
    return LidarrClient(settings.lidarr_url, settings.lidarr_api_key)


def _radarr() -> RadarrClient:
    return RadarrClient(settings.radarr_url, settings.radarr_api_key)


def _sonarr() -> SonarrClient:
    return SonarrClient(settings.sonarr_url, settings.sonarr_api_key)


__all__ = ["search_candidates", "ArrClientError"]
