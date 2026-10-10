"""Metadata enrichment runner.

Public surface: `enrich_movie`, `enrich_artist`, `enrich_album`. Each
loads a canonical row, calls the matching provider client(s), writes
the parsed data back to the row, sets `metadata_synced_at` plus
`metadata_status`, and commits. Idempotent: skips on TTL when
`force=False`. Catches `ProviderError`, tags the row failed, never
raises to the caller.

The functions are deliberately synchronous and do all DB work through
the caller's Session so they can run from APScheduler workers, the
backfill CLI, or in-process smoke tests without ceremony.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.movie import Movie
from app.models.music import Album, Artist
from app.models.tv import Series
from app.services.metadata._base import ProviderError
from app.services.metadata.musicbrainz import MusicBrainzClient
from app.services.metadata.tmdb import TMDBClient
from app.services.metadata.wikipedia import WikipediaClient


log = logging.getLogger("f7five0.metadata.runner")


Status = Literal["ok", "skipped", "no_external_id", "failed"]


@dataclass
class MetadataResult:
    status: Status
    provider: Optional[str] = None
    notes: Optional[str] = None


def _is_fresh(synced_at: Optional[datetime]) -> bool:
    if synced_at is None:
        return False
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced_at < timedelta(
        days=settings.metadata_ttl_days,
    )


# Known link kinds the UI's chip map handles. Anything else passes through
# as the raw kind so the frontend's fallback can render it capitalized.
_LINK_KIND_MAP = {
    "wikipedia": "wikipedia",
    "wikidata": "wikidata",
    "official homepage": "official",
    "official site": "official",
    "bandcamp": "bandcamp",
    "discogs": "discogs",
    "soundcloud": "soundcloud",
    "youtube": "youtube",
    "youtube music": "youtube",
    "free streaming": "streaming",
}


def _extract_links(relations: list[dict]) -> list[dict]:
    out: list[dict] = []
    for rel in relations or []:
        url = ((rel or {}).get("url") or {}).get("resource")
        if not url:
            continue
        kind = (rel.get("type") or "").lower()
        kind_normal = _LINK_KIND_MAP.get(kind, kind or "other")
        out.append({"kind": kind_normal, "url": url})
    return out


def _wiki_url_from_relations(relations: list[dict]) -> Optional[str]:
    for rel in relations or []:
        if (rel.get("type") or "").lower() == "wikipedia":
            url = ((rel or {}).get("url") or {}).get("resource")
            if url and "wikipedia.org" in url:
                return url
    return None


def _safe_year(value) -> Optional[int]:
    """Pull a 4-digit year out of `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`."""
    if not value:
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 9999 else None
    if isinstance(value, str):
        s = value.strip()[:4]
        if s.isdigit():
            return int(s)
    return None


# ---------------------------------------------------------------------------
# enrich_movie
# ---------------------------------------------------------------------------
def enrich_movie(
    db: Session, movie_id: uuid.UUID, force: bool = False,
) -> MetadataResult:
    movie = db.get(Movie, movie_id)
    if movie is None:
        return MetadataResult(status="failed", notes="movie_not_found")
    if not force and _is_fresh(movie.metadata_synced_at):
        return MetadataResult(status="skipped")
    if not movie.tmdb_id:
        movie.metadata_synced_at = datetime.now(timezone.utc)
        movie.metadata_status = "no_external_id"
        db.commit()
        return MetadataResult(status="no_external_id")

    try:
        with TMDBClient() as cli:
            payload = cli.get_movie(int(movie.tmdb_id))
    except ProviderError as exc:
        log.warning("tmdb fetch failed for movie %s: %s", movie.id, exc)
        movie.metadata_synced_at = datetime.now(timezone.utc)
        movie.metadata_status = "failed"
        db.commit()
        return MetadataResult(status="failed", provider="tmdb", notes=str(exc))

    if payload is None:
        # Either the key is unset or TMDB returned 404 for this id.
        movie.metadata_synced_at = datetime.now(timezone.utc)
        movie.metadata_status = "no_external_id"
        db.commit()
        return MetadataResult(status="no_external_id", provider="tmdb")

    credits = payload.get("credits") or {}
    raw_cast = credits.get("cast") or []
    raw_cast_sorted = sorted(
        raw_cast,
        key=lambda c: (c.get("order") if c.get("order") is not None else 9999),
    )
    cast_top = [
        {
            "name": c.get("name"),
            "character": c.get("character"),
            "order": c.get("order"),
            "profile_path": c.get("profile_path"),
        }
        for c in raw_cast_sorted[:10]
    ]
    crew = credits.get("crew") or []
    directors = [
        {"name": p.get("name"), "profile_path": p.get("profile_path")}
        for p in crew
        if (p.get("job") or "").lower() == "director"
    ]

    movie.tagline = payload.get("tagline") or None
    movie.movie_cast = cast_top
    movie.directors = directors
    rating = payload.get("vote_average")
    movie.tmdb_rating = float(rating) if isinstance(rating, (int, float)) else None
    votes = payload.get("vote_count")
    movie.tmdb_vote_count = int(votes) if isinstance(votes, (int, float)) else None
    movie.metadata_synced_at = datetime.now(timezone.utc)
    movie.metadata_status = "ok"
    db.commit()
    return MetadataResult(status="ok", provider="tmdb")


# ---------------------------------------------------------------------------
# enrich_artist
# ---------------------------------------------------------------------------
def enrich_artist(
    db: Session, artist_id: uuid.UUID, force: bool = False,
) -> MetadataResult:
    artist = db.get(Artist, artist_id)
    if artist is None:
        return MetadataResult(status="failed", notes="artist_not_found")
    if not force and _is_fresh(artist.metadata_synced_at):
        return MetadataResult(status="skipped")
    if not artist.mbid:
        artist.metadata_synced_at = datetime.now(timezone.utc)
        artist.metadata_status = "no_external_id"
        db.commit()
        return MetadataResult(status="no_external_id")

    try:
        with MusicBrainzClient() as mb:
            mb_payload = mb.get_artist(artist.mbid)
    except ProviderError as exc:
        log.warning("mb artist fetch failed for %s: %s", artist.id, exc)
        artist.metadata_synced_at = datetime.now(timezone.utc)
        artist.metadata_status = "failed"
        db.commit()
        return MetadataResult(
            status="failed", provider="musicbrainz", notes=str(exc),
        )

    if mb_payload is None:
        artist.metadata_synced_at = datetime.now(timezone.utc)
        artist.metadata_status = "no_external_id"
        db.commit()
        return MetadataResult(status="no_external_id", provider="musicbrainz")

    artist.country = mb_payload.get("country") or None
    artist.artist_type = mb_payload.get("type") or None
    life_span = mb_payload.get("life-span") or {}
    artist.formed_year = _safe_year(life_span.get("begin"))
    artist.disbanded_year = (
        _safe_year(life_span.get("end")) if life_span.get("ended") else None
    )
    relations = mb_payload.get("relations") or []
    artist.links = _extract_links(relations)

    bio_text: Optional[str] = None
    bio_source: Optional[str] = None
    wiki_url = _wiki_url_from_relations(relations)
    if wiki_url:
        try:
            with WikipediaClient() as wp:
                wiki_payload = wp.get_extract(wiki_url)
        except ProviderError as exc:
            log.warning("wikipedia fetch failed for %s: %s", artist.id, exc)
            wiki_payload = None
        if wiki_payload and wiki_payload.get("extract"):
            bio_text = wiki_payload.get("extract")
            bio_source = "wikipedia"
    if bio_text is None:
        annotation = mb_payload.get("annotation") or None
        if annotation:
            bio_text = annotation
            bio_source = "musicbrainz_annotation"
    if bio_text is None:
        bio_source = "none"

    artist.bio_text = bio_text
    artist.bio_source = bio_source
    artist.metadata_synced_at = datetime.now(timezone.utc)
    artist.metadata_status = "ok"
    db.commit()
    return MetadataResult(status="ok", provider="musicbrainz")


# ---------------------------------------------------------------------------
# enrich_album
# ---------------------------------------------------------------------------
def enrich_album(
    db: Session, album_id: uuid.UUID, force: bool = False,
) -> MetadataResult:
    album = db.get(Album, album_id)
    if album is None:
        return MetadataResult(status="failed", notes="album_not_found")
    if not force and _is_fresh(album.metadata_synced_at):
        return MetadataResult(status="skipped")
    if not album.mbid:
        album.metadata_synced_at = datetime.now(timezone.utc)
        album.metadata_status = "no_external_id"
        db.commit()
        return MetadataResult(status="no_external_id")

    try:
        with MusicBrainzClient() as mb:
            mb_payload = mb.get_release_group(album.mbid)
    except ProviderError as exc:
        log.warning("mb release-group fetch failed for %s: %s", album.id, exc)
        album.metadata_synced_at = datetime.now(timezone.utc)
        album.metadata_status = "failed"
        db.commit()
        return MetadataResult(
            status="failed", provider="musicbrainz", notes=str(exc),
        )

    if mb_payload is None:
        album.metadata_synced_at = datetime.now(timezone.utc)
        album.metadata_status = "no_external_id"
        db.commit()
        return MetadataResult(status="no_external_id", provider="musicbrainz")

    primary = mb_payload.get("primary-type")
    if primary:
        album.album_type = primary
    secondaries = mb_payload.get("secondary-types") or []
    album.secondary_types = [s for s in secondaries if isinstance(s, str)]
    disambiguation = mb_payload.get("disambiguation")
    if disambiguation is not None:
        album.disambiguation = disambiguation or None
    rating = (mb_payload.get("rating") or {}).get("value")
    album.mb_rating = float(rating) if isinstance(rating, (int, float)) else None
    relations = mb_payload.get("relations") or []
    album.links = _extract_links(relations)
    album.metadata_synced_at = datetime.now(timezone.utc)
    album.metadata_status = "ok"
    db.commit()
    return MetadataResult(status="ok", provider="musicbrainz")


# ---------------------------------------------------------------------------
# enrich_series
# ---------------------------------------------------------------------------
def _parse_date(value) -> Optional[date]:
    """Parse a `YYYY-MM-DD` string into a date, else None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def enrich_series(
    db: Session, series_id: uuid.UUID, force: bool = False,
) -> MetadataResult:
    """Populate a series from TMDB when it has a tmdb_id.

    Series are normally mirrored from Sonarr, which owns the next sync.
    This path gives Fix Match something to populate when Sonarr is not set
    up: it writes the canonical overview and first-aired date from TMDB and
    pulls a TMDB poster/backdrop into the art system when the series has no
    art yet (admin-set art is never overwritten). No external id or no key
    is a clean no-op, not a failure.
    """
    series = db.get(Series, series_id)
    if series is None:
        return MetadataResult(status="failed", notes="series_not_found")
    if not series.tmdb_id:
        return MetadataResult(status="no_external_id")

    try:
        with TMDBClient() as cli:
            payload = cli.get_series(int(series.tmdb_id))
    except ProviderError as exc:
        log.warning("tmdb tv fetch failed for series %s: %s", series.id, exc)
        return MetadataResult(status="failed", provider="tmdb", notes=str(exc))

    if payload is None:
        # Key unset or TMDB 404 for this id. Nothing to write.
        return MetadataResult(status="no_external_id", provider="tmdb")

    overview = payload.get("overview")
    if overview:
        series.overview = overview
    aired = _parse_date(payload.get("first_air_date"))
    if aired is not None:
        series.first_aired = aired
    db.commit()

    # Pull TMDB art only when the series has none; never clobber admin art.
    from app.models.art import ENTITY_SERIES, ROLE_BACKDROP, ROLE_POSTER
    from app.services.art import (
        SYSTEM_USER_ID, ArtValidationError, fetch_and_save_url,
    )
    from app.models.art import ArtOverride

    def _fetch_art(role: str, tmdb_path, size: str) -> None:
        if not tmdb_path:
            return
        if db.get(ArtOverride, (ENTITY_SERIES, series.id, role)) is not None:
            return
        try:
            fetch_and_save_url(
                db, entity_kind=ENTITY_SERIES, entity_id=series.id, role=role,
                url=f"https://image.tmdb.org/t/p/{size}{tmdb_path}",
                set_by_user_id=SYSTEM_USER_ID, source_kind="tmdb",
            )
        except ArtValidationError as exc:
            log.warning("tmdb art skipped for series %s %s: %s", series.id, role, exc)

    _fetch_art(ROLE_POSTER, payload.get("poster_path"), "w780")
    _fetch_art(ROLE_BACKDROP, payload.get("backdrop_path"), "w1280")
    db.commit()
    return MetadataResult(status="ok", provider="tmdb")
