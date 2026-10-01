"""Generated-playlist selection logic.

One module owns the SQL for every auto-playlist kind. The router in
app/api/auto_playlist.py is a thin layer that picks a helper, applies the
limit cap, and shapes the response. Each helper returns
(items, candidates_considered) so the endpoint can fold a `diagnostic`
block into the JSON without re-running the count query.

Items are QueueItem-shaped dicts, the same shape the frontend already
hands to `playAlbum` / `addToQueue`. That keeps `/mixes` from needing any
client-side adapter.

Filtering rules apply to every kind (per the design spec):
- track must have a media_files row
- the media_files row must have scan_state == 'ready'
- track duration must be >= 20 seconds (skits, stingers, intros are out)

A shared helper (`_playable_pool`) packages those rules so each kind
joins against the same source. We pick the first ready file per track
with DISTINCT ON so a track with multiple media_files rows doesn't show
up twice.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.music import Album, Artist, Track
from app.models.playback import WatchProgress

MIN_TRACK_DURATION_SEC = 20

# Tracks whose duration is unknown should still be playable; only filter
# when we know it's a skit. duration_sec is nullable on tracks.
_DURATION_OK = (Track.duration_sec.is_(None)) | (Track.duration_sec >= MIN_TRACK_DURATION_SEC)


def _playable_pool() -> Select:
    """Return a SELECT that yields the (track, album, artist, media_file)
    tuple for every playable track in the library.

    DISTINCT ON (Track.id) collapses tracks with multiple ready files to a
    single row (the lowest media_file id, which is stable). Used as a
    subquery by every selection helper so the filter is centralized.
    """
    return (
        select(
            Track.id.label("track_id"),
            Track.title.label("track_title"),
            Track.duration_sec.label("track_duration_sec"),
            Album.id.label("album_id"),
            Album.title.label("album_title"),
            Album.cover_path.label("album_cover_path"),
            Album.release_date.label("album_release_date"),
            Artist.id.label("artist_id"),
            Artist.name.label("artist_name"),
            MediaFile.id.label("media_file_id"),
            MediaFile.duration_sec.label("file_duration_sec"),
        )
        .distinct(Track.id)
        .select_from(Track)
        .join(Album, Album.id == Track.album_id)
        .join(Artist, Artist.id == Album.artist_id)
        .join(
            MediaFile,
            and_(
                MediaFile.kind == MediaKind.track,
                MediaFile.ref_id == Track.id,
                MediaFile.scan_state == ScanState.ready,
            ),
        )
        .where(_DURATION_OK)
        .order_by(Track.id, MediaFile.id)
    )


def _row_to_queue_item(row: Any) -> dict[str, Any]:
    """Shape a pool row into a QueueItem dict."""
    duration = row.track_duration_sec or row.file_duration_sec
    return {
        "media_file_id": str(row.media_file_id),
        "title": row.track_title,
        "artist_name": row.artist_name,
        "artist_id": str(row.artist_id),
        "album_title": row.album_title,
        "album_id": str(row.album_id),
        "cover_path": row.album_cover_path,
        "duration_sec": duration,
        "track_id": str(row.track_id),
    }


def _count_pool(db: Session) -> int:
    """How many candidate tracks survive the cross-cutting filter,
    library-wide. Used as the diagnostic baseline for kinds that don't
    pre-filter by parameter."""
    sub = _playable_pool().subquery()
    return int(db.scalar(select(func.count()).select_from(sub)) or 0)


def _count_subquery(db: Session, base: Select) -> int:
    return int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)


# ---------------------------------------------------------------------------
# Phase 5a kinds
# ---------------------------------------------------------------------------
def random_pick(db: Session, limit: int) -> tuple[list[dict[str, Any]], int]:
    pool = _playable_pool().subquery()
    stmt = select(pool).order_by(func.random()).limit(limit)
    rows = db.execute(stmt).all()
    return [_row_to_queue_item(r) for r in rows], _count_pool(db)


def by_artist(
    db: Session, artist_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int]:
    pool = _playable_pool().subquery()
    base = select(pool).where(pool.c.artist_id == artist_id)
    candidates = _count_subquery(db, base)
    rows = db.execute(base.order_by(func.random()).limit(limit)).all()
    return [_row_to_queue_item(r) for r in rows], candidates


def recently_added(db: Session, limit: int) -> tuple[list[dict[str, Any]], int]:
    """One row per album (most recent track wins), then plain order if
    we still have headroom. The dedup keeps a fresh import from dropping
    fifteen tracks of one album in a row.
    """
    pool = _playable_pool().subquery()
    rn = func.row_number().over(
        partition_by=pool.c.album_id,
        order_by=pool.c.media_file_id.desc(),
    ).label("rn")
    ranked = select(pool, rn).subquery()

    # First pass: take the freshest track per album in DESC media_file_id
    # order. media_file_id is created in ingest order so it tracks
    # "recently added" closely enough without needing created_at on Track.
    primary = (
        select(ranked)
        .where(ranked.c.rn == 1)
        .order_by(ranked.c.media_file_id.desc())
        .limit(limit)
    )
    primary_rows = db.execute(primary).all()
    seen = {r.media_file_id for r in primary_rows}
    items = [_row_to_queue_item(r) for r in primary_rows]

    if len(items) < limit:
        # Fall through to plain ordering for anything left so the page
        # still fills out on a small library.
        remaining = limit - len(items)
        fill = (
            select(pool)
            .order_by(pool.c.media_file_id.desc())
            .limit(remaining + len(seen))
        )
        for r in db.execute(fill).all():
            if r.media_file_id in seen:
                continue
            items.append(_row_to_queue_item(r))
            if len(items) >= limit:
                break

    return items, _count_pool(db)


def by_year(
    db: Session, year: int, limit: int,
) -> tuple[list[dict[str, Any]], int]:
    pool = _playable_pool().subquery()
    base = select(pool).where(
        func.extract("year", pool.c.album_release_date) == year,
    )
    candidates = _count_subquery(db, base)
    rows = db.execute(base.order_by(func.random()).limit(limit)).all()
    return [_row_to_queue_item(r) for r in rows], candidates


def by_decade(
    db: Session, decade: int, limit: int,
) -> tuple[list[dict[str, Any]], int]:
    pool = _playable_pool().subquery()
    start = decade
    end = decade + 9
    base = select(pool).where(
        func.extract("year", pool.c.album_release_date).between(start, end),
    )
    candidates = _count_subquery(db, base)
    rows = db.execute(base.order_by(func.random()).limit(limit)).all()
    return [_row_to_queue_item(r) for r in rows], candidates


def continue_listening(
    db: Session, user_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """In-progress audio tracks for the user, freshest first.

    Filters to track-kind media files with progress not yet completed.
    Joins through pool so a stale progress row pointing at a missing file
    drops out cleanly.
    """
    pool = _playable_pool().subquery()
    base = (
        select(pool)
        .join(WatchProgress, WatchProgress.media_file_id == pool.c.media_file_id)
        .where(
            WatchProgress.user_id == user_id,
            WatchProgress.completed_at.is_(None),
        )
        .order_by(WatchProgress.updated_at.desc())
        .limit(limit)
    )
    rows = db.execute(base).all()
    candidates = int(db.scalar(
        select(func.count())
        .select_from(WatchProgress)
        .where(
            WatchProgress.user_id == user_id,
            WatchProgress.completed_at.is_(None),
        )
    ) or 0)
    return [_row_to_queue_item(r) for r in rows], candidates


# ---------------------------------------------------------------------------
# Phase 5b: by-genre
# ---------------------------------------------------------------------------
def by_genre(
    db: Session, genre_slug: str, limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Albums whose `genres` JSONB array contains a string equal to the slug
    (case-insensitive). Resolves matching album ids via a dedicated query
    against jsonb_array_elements_text, then filters the playable pool.
    """
    slug = genre_slug.lower()
    album_ids = list(db.execute(
        text(
            "SELECT id FROM albums WHERE EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements_text(albums.genres) AS g"
            "  WHERE lower(g) = :slug"
            ")"
        ),
        {"slug": slug},
    ).scalars().all())

    if not album_ids:
        return [], 0

    pool = _playable_pool().subquery()
    base = select(pool).where(pool.c.album_id.in_(album_ids))
    candidates = _count_subquery(db, base)
    rows = db.execute(base.order_by(func.random()).limit(limit)).all()
    return [_row_to_queue_item(r) for r in rows], candidates


# ---------------------------------------------------------------------------
# Phase 5c: play-signal kinds + radio
# ---------------------------------------------------------------------------
def _user_has_plays(db: Session, user_id: uuid.UUID) -> bool:
    from app.models.track_play import TrackPlay  # local to avoid circular
    return bool(db.scalar(
        select(func.count())
        .select_from(TrackPlay)
        .where(TrackPlay.user_id == user_id)
    ))


def most_played(
    db: Session, user_id: uuid.UUID, limit: int, window: str = "all",
) -> tuple[list[dict[str, Any]], int, Optional[str]]:
    """Top tracks by play count for the calling user.

    `window` is one of "all" | "30d" | "90d". Tie-break on most recent play.
    Falls back to recently_added when the user has zero plays so the
    button never returns empty.
    """
    if not _user_has_plays(db, user_id):
        items, candidates = recently_added(db, limit)
        return items, candidates, "recently-added"

    from app.models.track_play import TrackPlay
    pool = _playable_pool().subquery()
    plays_q = select(
        TrackPlay.track_id.label("track_id"),
        func.count().label("play_count"),
        func.max(TrackPlay.played_at).label("last_played"),
    ).where(TrackPlay.user_id == user_id)
    if window == "30d":
        plays_q = plays_q.where(
            TrackPlay.played_at >= func.now() - text("interval '30 days'")
        )
    elif window == "90d":
        plays_q = plays_q.where(
            TrackPlay.played_at >= func.now() - text("interval '90 days'")
        )
    plays = plays_q.group_by(TrackPlay.track_id).subquery()

    base = (
        select(pool, plays.c.play_count, plays.c.last_played)
        .join(plays, plays.c.track_id == pool.c.track_id)
        .order_by(plays.c.play_count.desc(), plays.c.last_played.desc())
        .limit(limit)
    )
    rows = db.execute(base).all()
    items = [_row_to_queue_item(r) for r in rows]
    candidates = int(db.scalar(
        select(func.count(func.distinct(TrackPlay.track_id)))
        .where(TrackPlay.user_id == user_id)
    ) or 0)
    return items, candidates, None


def never_played(
    db: Session, user_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int, Optional[str]]:
    """Tracks the user has never played. Random within. Fallback to
    recently_added when the user has zero plays."""
    if not _user_has_plays(db, user_id):
        items, candidates = recently_added(db, limit)
        return items, candidates, "recently-added"

    from app.models.track_play import TrackPlay
    pool = _playable_pool().subquery()
    played = select(TrackPlay.track_id).where(TrackPlay.user_id == user_id)
    base = select(pool).where(pool.c.track_id.notin_(played))
    candidates = _count_subquery(db, base)
    rows = db.execute(base.order_by(func.random()).limit(limit)).all()
    return [_row_to_queue_item(r) for r in rows], candidates, None


def recently_played(
    db: Session, user_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Most recent distinct tracks the user has played, freshest first."""
    from app.models.track_play import TrackPlay
    pool = _playable_pool().subquery()
    last_play = (
        select(
            TrackPlay.track_id.label("track_id"),
            func.max(TrackPlay.played_at).label("last_played"),
        )
        .where(TrackPlay.user_id == user_id)
        .group_by(TrackPlay.track_id)
        .subquery()
    )
    base = (
        select(pool, last_play.c.last_played)
        .join(last_play, last_play.c.track_id == pool.c.track_id)
        .order_by(last_play.c.last_played.desc())
        .limit(limit)
    )
    rows = db.execute(base).all()
    candidates = int(db.scalar(
        select(func.count(func.distinct(TrackPlay.track_id)))
        .where(TrackPlay.user_id == user_id)
    ) or 0)
    return [_row_to_queue_item(r) for r in rows], candidates


def artist_radio(
    db: Session, user_id: uuid.UUID, artist_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int, Optional[str]]:
    """Mix of seed artist + neighbors that share at least one genre.

    Two-stage: ~30% seed share, the rest pulled from neighbor artists,
    capped per artist so one neighbor doesn't dominate. Falls back to
    by_artist when the seed has no genres.
    """
    seed = db.get(Artist, artist_id)
    if seed is None:
        return [], 0, None
    seed_genres_raw = list(seed.genres or [])
    seed_lower = [g.lower() for g in seed_genres_raw if isinstance(g, str)]

    if not seed_lower:
        items, candidates = by_artist(db, artist_id, limit)
        return items, candidates, "by-artist"

    seed_share = max(1, int(round(limit * 0.3)))
    seed_items, seed_pool = by_artist(db, artist_id, seed_share)

    # Find neighbor artists that share at least one genre. Lower-cased
    # comparison so casing in Lidarr doesn't fragment the taxonomy.
    neighbor_ids = list(db.execute(
        text(
            "SELECT a.id FROM artists a WHERE a.id != :seed_id AND EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements_text(a.genres) AS g"
            "  WHERE lower(g) = ANY(:slugs)"
            ")"
        ),
        {"seed_id": artist_id, "slugs": seed_lower},
    ).scalars().all())

    fill_target = limit - len(seed_items)
    fill_items: list[dict[str, Any]] = []
    if neighbor_ids and fill_target > 0:
        per_artist_cap = max(1, fill_target // max(1, len(neighbor_ids)) + 1)
        # row_number partitioned per artist, ordered randomly so a single
        # artist can't fill the queue.
        pool = _playable_pool().subquery()
        rn = func.row_number().over(
            partition_by=pool.c.artist_id,
            order_by=func.random(),
        ).label("rn")
        ranked = (
            select(pool, rn)
            .where(pool.c.artist_id.in_(neighbor_ids))
            .subquery()
        )
        fill = (
            select(ranked)
            .where(ranked.c.rn <= per_artist_cap)
            .order_by(func.random())
            .limit(fill_target)
        )
        fill_items = [_row_to_queue_item(r) for r in db.execute(fill).all()]

    items = _interleave(seed_items, fill_items)[:limit]
    candidates = seed_pool + len(fill_items)
    return items, candidates, None


# ---------------------------------------------------------------------------
# Phase 2: track similarity + track radio
# ---------------------------------------------------------------------------
def _similar_track_ids(
    db: Session, track_id: uuid.UUID, limit: int,
) -> list[uuid.UUID]:
    """Ordered similar track ids from the precomputed similarity graph.

    Highest score first. Returns [] when the seed track has no analysis /
    similarity edges yet (the caller falls back).
    """
    from app.models.audio_analysis import TrackSimilarity
    rows = db.execute(
        select(TrackSimilarity.similar_track_id)
        .where(TrackSimilarity.track_id == track_id)
        .order_by(TrackSimilarity.score.desc())
        .limit(limit)
    ).scalars().all()
    return list(rows)


def _pool_items_for_track_ids(
    db: Session, track_ids: list[uuid.UUID],
) -> list[dict[str, Any]]:
    """QueueItem dicts for the given track ids, preserving the input order.

    Only playable tracks (surviving the shared pool filter) come back, so a
    similar-but-unplayable track silently drops out.
    """
    if not track_ids:
        return []
    pool = _playable_pool().subquery()
    rows = db.execute(
        select(pool).where(pool.c.track_id.in_(track_ids))
    ).all()
    by_id = {r.track_id: r for r in rows}
    ordered: list[dict[str, Any]] = []
    for tid in track_ids:
        row = by_id.get(tid)
        if row is not None:
            ordered.append(_row_to_queue_item(row))
    return ordered


def similar_tracks(
    db: Session, track_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int, Optional[str]]:
    """Tracks most similar to `track_id` from the precomputed graph.

    Falls back to same-artist (then same-genre) picks when the seed has no
    similarity edges, so the endpoint never returns empty for a known track.
    Returns (items, candidates, fallback).
    """
    sim_ids = _similar_track_ids(db, track_id, limit)
    if sim_ids:
        items = _pool_items_for_track_ids(db, sim_ids)
        if items:
            return items, len(sim_ids), None

    # Fallback: same artist, then same genre. Resolve the seed's artist/genre
    # through the track -> album -> artist chain.
    track = db.get(Track, track_id)
    if track is None:
        return [], 0, None
    album = db.get(Album, track.album_id)
    if album is None:
        return [], 0, None

    items, candidates = by_artist(db, album.artist_id, limit)
    # Drop the seed track from its own radio.
    items = [it for it in items if it.get("track_id") != str(track_id)]
    if items:
        return items[:limit], candidates, "by-artist"

    # Last resort: genre pool via the album's first genre.
    genres = [g for g in (album.genres or []) if isinstance(g, str)]
    if genres:
        g_items, g_cand = by_genre(db, genres[0], limit)
        g_items = [it for it in g_items if it.get("track_id") != str(track_id)]
        if g_items:
            return g_items[:limit], g_cand, "by-genre"

    return [], candidates, "by-artist"


def track_radio(
    db: Session, track_id: uuid.UUID, limit: int,
) -> tuple[list[dict[str, Any]], int, Optional[str]]:
    """A radio queue seeded from one track.

    Leads with the seed track, then fills from its similarity graph. Falls back
    to same-artist / same-genre (via `similar_tracks`) when there are no edges.
    Returns (items, candidates, fallback).
    """
    seed_items = _pool_items_for_track_ids(db, [track_id])
    fill, candidates, fallback = similar_tracks(db, track_id, limit)
    # Don't duplicate the seed if the fallback surfaced it.
    fill = [it for it in fill if it.get("track_id") != str(track_id)]
    items = (seed_items + fill)[:limit]
    return items, candidates + len(seed_items), fallback


def _interleave(
    seed: list[dict[str, Any]], neighbors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Round-robin merge with neighbors weighted heavier so the queue
    sounds varied. Pattern: two neighbors, one seed, repeat."""
    out: list[dict[str, Any]] = []
    si = ni = 0
    while si < len(seed) or ni < len(neighbors):
        if ni < len(neighbors):
            out.append(neighbors[ni])
            ni += 1
        if ni < len(neighbors):
            out.append(neighbors[ni])
            ni += 1
        if si < len(seed):
            out.append(seed[si])
            si += 1
    return out
