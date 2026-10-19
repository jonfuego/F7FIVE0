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
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.movie import Movie
from app.models.music import Album, Artist
from app.models.tv import Series
from app.services import tmdb_key
from app.services.metadata._base import ProviderError
from app.services.metadata.musicbrainz import MusicBrainzClient
from app.services.metadata.tmdb import TMDBClient
from app.services.metadata.wikipedia import WikipediaClient
from app.services import metadata_locks


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


def _wikidata_url_from_relations(relations: list[dict]) -> Optional[str]:
    for rel in relations or []:
        if (rel.get("type") or "").lower() == "wikidata":
            url = ((rel or {}).get("url") or {}).get("resource")
            if url and "wikidata.org" in url:
                return url
    return None


def _link(links: Optional[list], kind: str, host: str) -> Optional[str]:
    """The first saved artist link of `kind` on `host` (artist.links shape)."""
    for item in links or []:
        if isinstance(item, dict) and item.get("kind") == kind:
            url = item.get("url") or ""
            if host in url:
                return url
    return None


def wikipedia_bio(
    wiki_url: Optional[str], wikidata_url: Optional[str],
) -> tuple[Optional[str], bool]:
    """The English Wikipedia summary for an artist: straight from a Wikipedia
    link when MusicBrainz has one, else Wikidata -> enwiki title -> summary
    (most MusicBrainz artists only link Wikidata, which is why bios were
    missing). Returns `(text, asked)`; `asked` is False when there was no
    link to follow. Raises ProviderError when a service cannot answer, so a
    caller can try again later instead of remembering a miss."""
    title_or_url = wiki_url
    if not title_or_url and wikidata_url:
        from app.services.metadata.wikidata import WikidataClient
        with WikidataClient() as wd:
            title_or_url = wd.enwiki_title(wikidata_url)
        if not title_or_url:
            return None, True
    if not title_or_url:
        return None, False
    with WikipediaClient() as wp:
        payload = wp.get_extract(title_or_url)
    text = (payload or {}).get("extract") or None
    return (text.strip() if isinstance(text, str) and text.strip() else None), True


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


def tmdb_genre_names(payload: Optional[dict]) -> list[str]:
    """Genre names from a TMDB movie record. TMDB sends `genres` as a list of
    `{"id": 18, "name": "Drama"}`; the library stores plain names (the same
    shape Radarr sync saves), in TMDB's order with duplicates and blanks
    dropped."""
    out: list[str] = []
    for g in (payload or {}).get("genres") or []:
        name = (g.get("name") if isinstance(g, dict) else g)
        if isinstance(name, str):
            name = name.strip()
            if name and name not in out:
                out.append(name)
    return out


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

    locked = metadata_locks.locked_fields(db, "movie", movie.id)
    if "title" not in locked:
        title = payload.get("title")
        if title:
            movie.title = title
    # An empty answer never wipes genres Radarr (or an earlier run) saved.
    genres = tmdb_genre_names(payload)
    if genres and "genres" not in locked:
        movie.genres = genres
    if "tagline" not in locked:
        movie.tagline = payload.get("tagline") or None
    movie.movie_cast = cast_top
    movie.directors = directors
    rating = payload.get("vote_average")
    movie.tmdb_rating = float(rating) if isinstance(rating, (int, float)) else None
    votes = payload.get("vote_count")
    movie.tmdb_vote_count = int(votes) if isinstance(votes, (int, float)) else None
    movie.metadata_synced_at = datetime.now(timezone.utc)
    movie.metadata_status = "ok"

    # Save TMDB collection membership (not lockable; always written).
    coll = payload.get("belongs_to_collection")
    if coll and isinstance(coll, dict) and coll.get("id"):
        movie.tmdb_collection_id = int(coll["id"])
        movie.tmdb_collection_name = coll.get("name") or None
    else:
        movie.tmdb_collection_id = None
        movie.tmdb_collection_name = None
    movie.tmdb_collection_checked_at = datetime.now(timezone.utc)

    db.commit()
    # Sync collections after the commit so the new row is visible.
    try:
        from app import scheduler
        scheduler.trigger_collections_sync(delay_sec=5)
    except Exception:
        pass
    return MetadataResult(status="ok", provider="tmdb")


def backfill_movie_genres(
    db: Session, *, batch_size: int = 25, pause_sec: float = 0.0,
) -> int:
    """Fill `genres` for TMDB-matched movies that have none. Enrichment
    skipped genres before, so movies already enriched keep an empty list and
    their `metadata_synced_at` is fresh; this reads TMDB for them directly
    (the disk cache answers movies enriched within the TTL without a request)
    and touches nothing but `genres`. Walks the table by id in batches of
    `batch_size`, commits each batch, and waits `pause_sec` after every movie it
    has to look up so a big library stays polite. A movie TMDB cannot answer
    for (no key, 404, error) is left as it is and tried on the next run.
    Safe to rerun: movies that have genres are never read again, so a second
    run saves nothing. Returns the number of movies that got genres."""
    if not tmdb_key.get():
        return 0
    filled = 0
    last_id = None
    with TMDBClient() as cli:
        while True:
            stmt = (
                select(Movie.id, Movie.genres)
                .where(Movie.tmdb_id.is_not(None))
                .order_by(Movie.id)
                .limit(batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(Movie.id > last_id)
            rows = db.execute(stmt).all()
            if not rows:
                break
            last_id = rows[-1][0]
            for movie_id, current in rows:
                if current:
                    continue
                movie = db.get(Movie, movie_id)
                if movie is None or movie.genres or not movie.tmdb_id:
                    continue
                try:
                    payload = cli.get_movie(int(movie.tmdb_id))
                except ProviderError as exc:
                    log.warning("tmdb genres fetch failed for movie %s: %s", movie.id, exc)
                    payload = None
                names = tmdb_genre_names(payload)
                if names and not metadata_locks.is_locked(db, "movie", movie.id, "genres"):
                    movie.genres = names
                    filled += 1
                if pause_sec > 0:
                    time.sleep(pause_sec)
            db.commit()
    return filled


# ---------------------------------------------------------------------------
# Collections backfill
# ---------------------------------------------------------------------------
def backfill_movie_collections(
    db: Session, *, batch_size: int = 25, pause_sec: float = 0.25,
) -> int:
    """Fill tmdb_collection_id/name for movies that have a tmdb_id but have never
    been checked for collection membership. Walks by id in batches, sets
    tmdb_collection_checked_at regardless of whether the movie is in a collection
    (so a second run skips it). A failed TMDB lookup leaves checked_at null for
    retry. Returns the number of movies that received a collection."""
    if not tmdb_key.get():
        return 0
    filled = 0
    last_id = None
    with TMDBClient() as cli:
        while True:
            stmt = (
                select(Movie.id)
                .where(
                    Movie.tmdb_id.is_not(None),
                    Movie.tmdb_collection_checked_at.is_(None),
                )
                .order_by(Movie.id)
                .limit(batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(Movie.id > last_id)
            rows = db.scalars(stmt).all()
            if not rows:
                break
            last_id = rows[-1]
            for movie_id in rows:
                movie = db.get(Movie, movie_id)
                if movie is None or not movie.tmdb_id:
                    continue
                try:
                    payload = cli.get_movie(int(movie.tmdb_id))
                except ProviderError as exc:
                    log.warning("tmdb collections fetch failed for movie %s: %s", movie.id, exc)
                    if pause_sec > 0:
                        time.sleep(pause_sec)
                    continue
                coll = (payload or {}).get("belongs_to_collection")
                if coll and isinstance(coll, dict) and coll.get("id"):
                    movie.tmdb_collection_id = int(coll["id"])
                    movie.tmdb_collection_name = coll.get("name") or None
                    filled += 1
                movie.tmdb_collection_checked_at = datetime.now(timezone.utc)
                if pause_sec > 0:
                    time.sleep(pause_sec)
            db.commit()
    return filled


# ---------------------------------------------------------------------------
# Artist bios (Wikipedia, through Wikidata)
# ---------------------------------------------------------------------------
# bio_source for an artist whose Wikipedia / Wikidata link led to no English
# article: remembered so the backfill does not ask again.
BIO_NOT_FOUND = "not_found"


def backfill_artist_bios(
    db: Session, *, batch_size: int = 25, pause_sec: float = 0.0,
    max_failures: int = 5,
) -> int:
    """Fill `bio_text` for artists that have none but whose saved links point
    at Wikipedia or Wikidata. Enrichment only followed a direct Wikipedia
    link, and MusicBrainz links most artists to Wikidata instead, so most
    artists never got a bio; enrichment also skips artists within its TTL, so
    this reads the saved `links` (no MusicBrainz request) and touches only
    `bio_text` / `bio_source`. Walks by id in batches, commits each batch,
    waits `pause_sec` after each artist it asks about. A miss is remembered
    (`bio_source` = BIO_NOT_FOUND); a service error is not, and
    `max_failures` errors in a row end the run. Safe to rerun: an artist with
    a bio or a remembered miss is never asked again. Returns how many got a
    bio."""
    filled = 0
    failures = 0
    last_id = None
    while True:
        stmt = (
            select(Artist.id)
            .where(Artist.bio_text.is_(None))
            .where((Artist.bio_source.is_(None)) | (Artist.bio_source != BIO_NOT_FOUND))
            .order_by(Artist.id)
            .limit(batch_size)
        )
        if last_id is not None:
            stmt = stmt.where(Artist.id > last_id)
        ids = list(db.scalars(stmt))
        if not ids:
            break
        last_id = ids[-1]
        for artist_id in ids:
            artist = db.get(Artist, artist_id)
            if artist is None or artist.bio_text:
                continue
            wiki = _link(artist.links, "wikipedia", "wikipedia.org")
            wikidata = _link(artist.links, "wikidata", "wikidata.org")
            if not wiki and not wikidata:
                continue
            try:
                text, _asked = wikipedia_bio(wiki, wikidata)
            except ProviderError as exc:
                failures += 1
                log.info("artist bio backfill: %r failed: %s", artist.name, exc)
                if failures >= max_failures:
                    db.commit()
                    log.warning("artist bio backfill: stopping after %d failures", failures)
                    return filled
                continue
            failures = 0
            if text:
                artist.bio_text = text
                artist.bio_source = "wikipedia"
                filled += 1
            else:
                artist.bio_source = BIO_NOT_FOUND
            if pause_sec > 0:
                time.sleep(pause_sec)
        db.commit()
    return filled


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

    locked = metadata_locks.locked_fields(db, "artist", artist.id)
    if "country" not in locked:
        artist.country = mb_payload.get("country") or None
    artist.artist_type = mb_payload.get("type") or None
    life_span = mb_payload.get("life-span") or {}
    if "formed_year" not in locked:
        artist.formed_year = _safe_year(life_span.get("begin"))
    if "disbanded_year" not in locked:
        artist.disbanded_year = (
            _safe_year(life_span.get("end")) if life_span.get("ended") else None
        )
    relations = mb_payload.get("relations") or []
    artist.links = _extract_links(relations)

    bio_text: Optional[str] = None
    bio_source: Optional[str] = None
    asked = False
    lookup_failed = False
    try:
        bio_text, asked = wikipedia_bio(
            _wiki_url_from_relations(relations),
            _wikidata_url_from_relations(relations),
        )
    except ProviderError as exc:
        # Not a miss: leave bio_source empty so the bio backfill tries again.
        lookup_failed = True
        log.warning("wikipedia bio fetch failed for %s: %s", artist.id, exc)
    if bio_text is not None:
        bio_source = "wikipedia"
    if bio_text is None and lookup_failed and artist.bio_text:
        # A service error must not wipe a bio the artist already has.
        bio_text, bio_source = artist.bio_text, artist.bio_source
    if bio_text is None:
        annotation = mb_payload.get("annotation") or None
        if annotation:
            bio_text = annotation
            bio_source = "musicbrainz_annotation"
    if bio_text is None and bio_source is None and asked:
        # A Wikipedia or Wikidata link that led to no English article.
        bio_source = BIO_NOT_FOUND

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

    locked = metadata_locks.locked_fields(db, "series", series.id)
    overview = payload.get("overview")
    if overview and "overview" not in locked:
        series.overview = overview
    aired = _parse_date(payload.get("first_air_date"))
    if aired is not None and "first_aired" not in locked:
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
