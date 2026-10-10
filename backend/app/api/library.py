"""Library read endpoints.

These are the "what's in my library" calls for Phase 1. All require an
authenticated user (any role). No write operations here — sync is the only
thing that mutates library rows.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from datetime import datetime, timezone

from app import scheduler
from app.api.deps import current_user, get_db, require_admin
from app.api.schemas import (
    AlbumDetailOut, AlbumOut, ContinueWatchingItemOut, EpisodeOut,
    MediaFileOut, MovieDetailOut, MovieOut, MusicArtistDetailOut,
    MusicArtistOut, MusicVideoArtistDetailOut, MusicVideoArtistOut,
    MediaMarkerOut, MusicVideoOut, MusicVideoReleaseDetailOut,
    MusicVideoReleaseOut, NewArrivalsBadgeOut, OnDeckItemOut, ProgressOut,
    ProgressUpsertRequest, RecentItemOut, RecentMusicVideoOut,
    SearchResultOut, SeriesDetailOut, SeriesOut, SongRowOut, TrackOut,
    TrackPlayCreateRequest, TrackPlayOut,
)
from app.models.art import (
    ENTITY_ALBUM, ENTITY_ARTIST, ENTITY_MOVIE, ENTITY_MUSIC_VIDEO, ENTITY_SERIES,
    ROLE_BACKDROP, ROLE_COVER, ROLE_POSTER, ROLE_THUMB,
)
from app.models.markers import MediaMarker
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import (
    Album, Artist, MusicVideo, MusicVideoRelease, Track,
)
from app.models.playback import WatchProgress
from app.models.track_play import TrackPlay
from app.models.tv import Episode, Series
from app.models.user import User
from app.services import scan_status
from app.services.art import resolve_art, resolve_art_batch


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards in a user search term.

    Without this, a `%` or `_` typed by the user acts as a SQL wildcard, so
    "100%" matches everything. Backslash is the escape char; callers pass
    `escape="\\"` to the `.like()` so these stay literal. Escape the
    backslash itself first so an escape char in the term can't be smuggled.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sort_expr(name_col, override_col=None):
    """Article-stripped, case-folded sort expression.

    Drops a leading "the ", "a ", or "an " so titles file under their first
    real word. Postgres only; the `'i'` flag is regexp_replace's
    case-insensitive switch and SQLAlchemy passes it through verbatim.
    """
    base = func.coalesce(override_col, name_col) if override_col is not None else name_col
    return func.regexp_replace(func.lower(base), r'^(the|a|an)\s+', '', 'i')


def merge_overrides(entity) -> dict:
    """Effective values dict overlaying entity.overrides JSONB on canonical columns.

    Keys returned: display_name, tagline, year, runtime_min, rating.
    Each reads from `entity.overrides[key]` when present, otherwise the
    matching canonical attribute. `display_name` falls back to `title` or
    `name` depending on which the entity carries; `year` walks `year ->
    first_aired.year -> release_year -> release_date.year`; `rating`
    walks `tmdb_rating -> mb_rating`. Callers project whichever keys
    they need.
    """
    overrides = getattr(entity, "overrides", None) or {}

    def _coalesce(key, *fallbacks):
        v = overrides.get(key)
        if v is not None and v != "":
            return v
        for fb in fallbacks:
            if fb is not None and fb != "":
                return fb
        return None

    canonical_name = getattr(entity, "title", None)
    if canonical_name is None:
        canonical_name = getattr(entity, "name", None)

    canonical_year = getattr(entity, "year", None)
    if canonical_year is None:
        first_aired = getattr(entity, "first_aired", None)
        if first_aired is not None:
            canonical_year = first_aired.year
    if canonical_year is None:
        canonical_year = getattr(entity, "release_year", None)
    if canonical_year is None:
        release_date = getattr(entity, "release_date", None)
        if release_date is not None:
            canonical_year = release_date.year

    return {
        "display_name": _coalesce("display_name", canonical_name),
        "tagline": _coalesce("tagline", getattr(entity, "tagline", None)),
        "year": _coalesce("year", canonical_year),
        "runtime_min": _coalesce("runtime_min", getattr(entity, "runtime_min", None)),
        "rating": _coalesce(
            "rating",
            getattr(entity, "tmdb_rating", None),
            getattr(entity, "mb_rating", None),
        ),
    }


# Fraction of duration that marks an item "watched". Below this threshold we
# surface it on the Continue Watching shelf; at or above, we hide it and stamp
# completed_at. Matches the informal "credits-rolled" convention.
COMPLETED_FRACTION = 0.90
# Minimum seconds into a file before we consider it worth tracking. Avoids
# CW spam from a misclick: the user has to actually commit to watching.
MIN_PROGRESS_SECONDS = 30


router = APIRouter()


def _ready_files_subq(parent_id_col, kind: MediaKind):
    """Correlated EXISTS for at least one ready MediaFile under parent_id_col."""
    from sqlalchemy import exists, select as _sel
    return exists(
        _sel(MediaFile.id)
        .where(MediaFile.kind == kind)
        .where(MediaFile.ref_id == parent_id_col)
        .where(MediaFile.scan_state == ScanState.ready)
    )


def _allow_pending(include_pending: bool, user: User) -> bool:
    if not include_pending:
        return False
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return True


def _files_by_ref(
    db: Session, kind: MediaKind, ref_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, list[MediaFile]]:
    """Fetch all media files for a set of refs and group by ref_id."""
    ids = list(ref_ids)
    if not ids:
        return {}
    rows = db.scalars(
        select(MediaFile).where(
            MediaFile.kind == kind,
            MediaFile.ref_id.in_(ids),
        )
    ).all()
    out: dict[uuid.UUID, list[MediaFile]] = {}
    for mf in rows:
        out.setdefault(mf.ref_id, []).append(mf)
    return out


def _mf_out(mf: MediaFile) -> MediaFileOut:
    return MediaFileOut(
        id=mf.id,
        path=mf.path,
        container=mf.container,
        size_bytes=mf.size_bytes,
        video_codec=mf.video_codec,
        audio_codec=mf.audio_codec,
        audio_channels=mf.audio_channels,
        width=mf.width,
        height=mf.height,
        duration_sec=mf.duration_sec,
        bitrate_kbps=mf.bitrate_kbps,
        scan_state=mf.scan_state.value,
    )


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------
@router.get("/movies", response_model=list[MovieOut])
def list_movies(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(200, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(False),
) -> list[MovieOut]:
    skip_filter = _allow_pending(include_pending, user)
    stmt = select(Movie).order_by(_sort_expr(Movie.title, Movie.sort_title))
    if not skip_filter:
        stmt = stmt.where(_ready_files_subq(Movie.id, MediaKind.movie))
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    files = _files_by_ref(db, MediaKind.movie, (m.id for m in rows))
    movie_ids = [m.id for m in rows]
    posters = resolve_art_batch(
        db, entity_kind=ENTITY_MOVIE, entity_ids=movie_ids, role=ROLE_POSTER,
    )
    backdrops = resolve_art_batch(
        db, entity_kind=ENTITY_MOVIE, entity_ids=movie_ids, role=ROLE_BACKDROP,
    )
    return [
        MovieOut.model_validate({
            **{k: getattr(m, k) for k in (
                "id", "overview", "tmdb_id", "imdb_id", "radarr_id",
                "genres", "tmdb_vote_count",
                "metadata_synced_at", "metadata_status", "created_at",
            )},
            **_movie_merged_fields(m),
            "poster_path": posters.get(m.id),
            "backdrop_path": backdrops.get(m.id),
            "media_files": [_mf_out(f) for f in files.get(m.id, [])],
        })
        for m in rows
    ]


def _movie_merged_fields(m) -> dict:
    """Movie response keys that respect overrides JSONB.

    Wraps `merge_overrides` to project the keys MovieOut wants. The wire
    field name `tmdb_rating` is preserved so older frontend builds keep
    rendering; only the value reflects the override when set.
    """
    eff = merge_overrides(m)
    return {
        "title": eff["display_name"],
        "year": eff["year"],
        "runtime_min": eff["runtime_min"],
        "tagline": eff["tagline"],
        "tmdb_rating": eff["rating"],
    }


@router.get("/movies/{movie_id}", response_model=MovieDetailOut)
def get_movie(
    movie_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> MovieDetailOut:
    skip_filter = _allow_pending(include_pending, user)
    m = db.get(Movie, movie_id)
    if m is None:
        raise HTTPException(status_code=404, detail="movie_not_found")
    files = _files_by_ref(db, MediaKind.movie, [m.id])
    if not skip_filter and not any(
        f.scan_state == ScanState.ready for f in files.get(m.id, [])
    ):
        raise HTTPException(status_code=404, detail="movie_not_found")
    return MovieDetailOut.model_validate({
        **{k: getattr(m, k) for k in (
            "id", "overview", "tmdb_id", "imdb_id", "radarr_id",
            "genres", "tmdb_vote_count",
            "metadata_synced_at", "metadata_status",
            "sort_title",
        )},
        **_movie_merged_fields(m),
        "poster_path": resolve_art(
            db,
            entity_kind=ENTITY_MOVIE,
            entity_id=m.id,
            role=ROLE_POSTER,
        ),
        "backdrop_path": resolve_art(
            db,
            entity_kind=ENTITY_MOVIE,
            entity_id=m.id,
            role=ROLE_BACKDROP,
        ),
        "media_files": [_mf_out(f) for f in files.get(m.id, [])],
        # Heavy JSONB columns. The DB attribute is `movie_cast` to dodge the
        # Python builtin / SQL keyword shadow; the JSON output uses `cast`.
        "cast": m.movie_cast or [],
        "directors": m.directors or [],
    })


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------
@router.get("/series", response_model=list[SeriesOut])
def list_series(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(200, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(False),
) -> list[SeriesOut]:
    skip_filter = _allow_pending(include_pending, user)
    stmt = select(Series).order_by(_sort_expr(Series.title, Series.sort_title))
    if not skip_filter:
        stmt = stmt.where(
            exists(
                select(Episode.id)
                .join(
                    MediaFile,
                    (MediaFile.kind == MediaKind.episode)
                    & (MediaFile.ref_id == Episode.id),
                )
                .where(Episode.series_id == Series.id)
                .where(MediaFile.scan_state == ScanState.ready)
            )
        )
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    series_ids = [s.id for s in rows]
    posters = resolve_art_batch(
        db, entity_kind=ENTITY_SERIES, entity_ids=series_ids, role=ROLE_POSTER,
    )
    backdrops = resolve_art_batch(
        db, entity_kind=ENTITY_SERIES, entity_ids=series_ids, role=ROLE_BACKDROP,
    )
    return [
        SeriesOut.model_validate({
            **{k: getattr(s, k) for k in (
                "id", "overview", "tvdb_id", "tmdb_id", "sonarr_id", "created_at",
            )},
            **_series_merged_fields(s),
            "poster_path": posters.get(s.id),
            "backdrop_path": backdrops.get(s.id),
        })
        for s in rows
    ]


def _series_merged_fields(s) -> dict:
    """Series response keys that respect overrides JSONB."""
    eff = merge_overrides(s)
    return {
        "title": eff["display_name"],
        "year": eff["year"],
    }


@router.get("/series/{series_id}", response_model=SeriesDetailOut)
def get_series(
    series_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> SeriesDetailOut:
    skip_filter = _allow_pending(include_pending, user)
    series = db.scalar(
        select(Series)
        .where(Series.id == series_id)
        .options(selectinload(Series.episodes))
    )
    if series is None:
        raise HTTPException(status_code=404, detail="series_not_found")

    files = _files_by_ref(db, MediaKind.episode, (e.id for e in series.episodes))
    all_episodes = sorted(
        series.episodes, key=lambda e: (e.season_number, e.episode_number),
    )
    if skip_filter:
        episodes = all_episodes
    else:
        episodes = [
            e for e in all_episodes
            if any(f.scan_state == ScanState.ready for f in files.get(e.id, []))
        ]
        if not episodes:
            raise HTTPException(status_code=404, detail="series_not_found")
    return SeriesDetailOut.model_validate({
        **{k: getattr(series, k) for k in (
            "id", "overview", "tvdb_id", "tmdb_id", "sonarr_id",
            "sort_title",
        )},
        **_series_merged_fields(series),
        "poster_path": resolve_art(
            db,
            entity_kind=ENTITY_SERIES,
            entity_id=series.id,
            role=ROLE_POSTER,
        ),
        "backdrop_path": resolve_art(
            db,
            entity_kind=ENTITY_SERIES,
            entity_id=series.id,
            role=ROLE_BACKDROP,
        ),
        "episodes": [
            EpisodeOut.model_validate({
                "id": e.id,
                "season_number": e.season_number,
                "episode_number": e.episode_number,
                "title": e.title,
                "overview": e.overview,
                "media_files": [_mf_out(f) for f in files.get(e.id, [])],
            })
            for e in episodes
        ],
    })


# ---------------------------------------------------------------------------
# Albums
# ---------------------------------------------------------------------------
@router.get("/albums", response_model=list[AlbumOut])
def list_albums(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    artist_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(200, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(False),
) -> list[AlbumOut]:
    # Default sort is artist then chronological within the artist's
    # discography. Explicit join so ORDER BY sees Artist.name; selectinload
    # still batches the artist fetch for the projection below so we avoid
    # N+1 at list sizes of 200+.
    skip_filter = _allow_pending(include_pending, user)
    stmt = (
        select(Album)
        .join(Album.artist)
        .options(selectinload(Album.artist))
        .order_by(
            _sort_expr(Artist.name, Artist.sort_name),
            Album.release_date.asc().nulls_last(),
            _sort_expr(Album.title, Album.sort_title),
        )
    )
    if artist_id is not None:
        stmt = stmt.where(Album.artist_id == artist_id)
    if not skip_filter:
        stmt = stmt.where(
            exists(
                select(Track.id)
                .join(
                    MediaFile,
                    (MediaFile.kind == MediaKind.track)
                    & (MediaFile.ref_id == Track.id),
                )
                .where(Track.album_id == Album.id)
                .where(MediaFile.scan_state == ScanState.ready)
            )
        )
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    covers = resolve_art_batch(
        db, entity_kind=ENTITY_ALBUM, entity_ids=[a.id for a in rows],
        role=ROLE_COVER,
    )
    return [
        AlbumOut.model_validate({
            "id": a.id,
            "artist_id": a.artist_id,
            "artist_name": _effective_name(a.artist) if a.artist is not None else None,
            "title": merge_overrides(a)["display_name"],
            "release_date": a.release_date,
            "cover_path": covers.get(a.id),
            "album_type": a.album_type,
            "metadata_synced_at": a.metadata_synced_at,
            "metadata_status": a.metadata_status,
            "created_at": a.created_at,
        })
        for a in rows
    ]


def _effective_name(entity) -> Optional[str]:
    """Override-aware display name for an entity that uses `name`/`title`."""
    return merge_overrides(entity)["display_name"]


@router.get("/albums/{album_id}", response_model=AlbumDetailOut)
def get_album(
    album_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> AlbumDetailOut:
    skip_filter = _allow_pending(include_pending, user)
    album = db.scalar(
        select(Album)
        .where(Album.id == album_id)
        .options(selectinload(Album.tracks))
    )
    if album is None:
        raise HTTPException(status_code=404, detail="album_not_found")

    files = _files_by_ref(db, MediaKind.track, (t.id for t in album.tracks))
    all_tracks = sorted(
        album.tracks, key=lambda t: (t.disc_number or 1, t.track_number or 0),
    )
    if skip_filter:
        tracks = all_tracks
    else:
        tracks = [
            t for t in all_tracks
            if any(f.scan_state == ScanState.ready for f in files.get(t.id, []))
        ]
        if not tracks:
            raise HTTPException(status_code=404, detail="album_not_found")
    artist = db.scalar(select(Artist).where(Artist.id == album.artist_id))
    return AlbumDetailOut.model_validate({
        "id": album.id,
        "artist_id": album.artist_id,
        "artist_name": _effective_name(artist) if artist is not None else None,
        "title": merge_overrides(album)["display_name"],
        "release_date": album.release_date,
        "cover_path": resolve_art(
            db, entity_kind=ENTITY_ALBUM, entity_id=album.id, role=ROLE_COVER,
        ),
        "album_type": album.album_type,
        "metadata_synced_at": album.metadata_synced_at,
        "metadata_status": album.metadata_status,
        "secondary_types": album.secondary_types or [],
        "label": album.label,
        "disambiguation": album.disambiguation,
        "mb_rating": merge_overrides(album)["rating"],
        "links": album.links or [],
        "tracks": [
            TrackOut.model_validate({
                "id": t.id,
                "title": merge_overrides(t)["display_name"],
                "track_number": t.track_number,
                "disc_number": t.disc_number,
                "duration_sec": t.duration_sec,
                "media_files": [_mf_out(f) for f in files.get(t.id, [])],
            })
            for t in tracks
        ],
    })


# ---------------------------------------------------------------------------
# Songs (flat track index)
# ---------------------------------------------------------------------------
@router.get("/songs", response_model=list[SongRowOut])
def list_songs(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: Optional[str] = Query(default=None, max_length=200),
    artist_id: uuid.UUID | None = Query(default=None),
    album_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(200, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    include_pending: bool = Query(False),
) -> list[SongRowOut]:
    """Flat searchable list of every track. Denormalized so the frontend
    can build queue items without N+1 calls.

    Sort is alphabetical by title (case-insensitive) with `Track.id` as a
    stable tiebreaker for pagination. Tracks with no ready file are
    hidden by default; admin callers can pass include_pending=true to see
    the full set.
    """
    skip_filter = _allow_pending(include_pending, user)
    stmt = (
        select(Track)
        .join(Track.album)
        .join(Album.artist)
        .options(selectinload(Track.album).selectinload(Album.artist))
        .order_by(_sort_expr(Track.title, Track.sort_title), Track.id)
    )
    if q is not None and q.strip():
        stmt = stmt.where(func.lower(Track.title).like(f"%{q.strip().lower()}%"))
    if artist_id is not None:
        stmt = stmt.where(Album.artist_id == artist_id)
    if album_id is not None:
        stmt = stmt.where(Track.album_id == album_id)
    if not skip_filter:
        stmt = stmt.where(_ready_files_subq(Track.id, MediaKind.track))
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    files = _files_by_ref(db, MediaKind.track, (t.id for t in rows))
    song_covers = resolve_art_batch(
        db, entity_kind=ENTITY_ALBUM,
        entity_ids={t.album_id for t in rows}, role=ROLE_COVER,
    )
    return [
        SongRowOut(
            id=t.id,
            title=merge_overrides(t)["display_name"],
            track_number=t.track_number,
            disc_number=t.disc_number,
            duration_sec=t.duration_sec,
            album_id=t.album_id,
            album_title=merge_overrides(t.album)["display_name"],
            cover_path=song_covers.get(t.album_id),
            artist_id=t.album.artist_id,
            artist_name=_effective_name(t.album.artist) or "" if t.album.artist is not None else "",
            media_files=[_mf_out(f) for f in files.get(t.id, [])],
        )
        for t in rows
    ]


# ---------------------------------------------------------------------------
# Music artists (default view for /music)
# ---------------------------------------------------------------------------
@router.get("/artists", response_model=list[MusicArtistOut])
def list_music_artists(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> list[MusicArtistOut]:
    """Artists that have at least one Album row.

    Mirrors /music-videos/artists: one card per artist with an
    `album_count` so the grid renders '12 albums' without a per-artist
    follow-up. Case-insensitive name order for stable sort regardless of
    leading-caps quirks in Lidarr metadata.
    """
    skip_filter = _allow_pending(include_pending, user)
    stmt = (
        select(
            Artist,
            func.count(Album.id).label("album_count"),
        )
        .join(Album, Album.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(_sort_expr(Artist.name, Artist.sort_name))
    )
    if not skip_filter:
        TrackAlbum = aliased(Album)
        stmt = stmt.where(
            exists(
                select(Track.id)
                .join(TrackAlbum, TrackAlbum.id == Track.album_id)
                .join(
                    MediaFile,
                    (MediaFile.kind == MediaKind.track)
                    & (MediaFile.ref_id == Track.id),
                )
                .where(TrackAlbum.artist_id == Artist.id)
                .where(MediaFile.scan_state == ScanState.ready)
            )
        )
    rows = db.execute(stmt).all()
    artist_thumbs = resolve_art_batch(
        db,
        entity_kind=ENTITY_ARTIST,
        entity_ids=[ar.id for ar, _ in rows],
        role=ROLE_THUMB,
    )
    return [
        MusicArtistOut(
            id=ar.id,
            name=_effective_name(ar) or ar.name,
            image_path=artist_thumbs.get(ar.id),
            album_count=int(album_count),
            country=ar.country,
            artist_type=ar.artist_type,
            formed_year=ar.formed_year,
            disbanded_year=ar.disbanded_year,
            bio_source=ar.bio_source,
            metadata_synced_at=ar.metadata_synced_at,
            metadata_status=ar.metadata_status,
        )
        for ar, album_count in rows
    ]


@router.get("/artists/{artist_id}", response_model=MusicArtistDetailOut)
def get_music_artist(
    artist_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> MusicArtistDetailOut:
    """Artist detail plus the full discography.

    Albums are release-date ascending with null dates pushed to the end,
    tiebreaking on case-insensitive title. Keeps the grouping intuitive
    for browsing: earliest studio records first, compilations and
    unknown-date releases trailing.
    """
    skip_filter = _allow_pending(include_pending, user)
    artist = db.get(Artist, artist_id)
    if artist is None:
        raise HTTPException(status_code=404, detail="artist_not_found")

    albums_stmt = (
        select(Album)
        .where(Album.artist_id == artist.id)
        .order_by(
            Album.release_date.asc().nulls_last(),
            _sort_expr(Album.title, Album.sort_title),
        )
    )
    if not skip_filter:
        albums_stmt = albums_stmt.where(
            exists(
                select(Track.id)
                .join(
                    MediaFile,
                    (MediaFile.kind == MediaKind.track)
                    & (MediaFile.ref_id == Track.id),
                )
                .where(Track.album_id == Album.id)
                .where(MediaFile.scan_state == ScanState.ready)
            )
        )
    albums = list(db.scalars(albums_stmt))
    if not skip_filter and not albums:
        raise HTTPException(status_code=404, detail="artist_not_found")

    album_covers = resolve_art_batch(
        db, entity_kind=ENTITY_ALBUM, entity_ids=[a.id for a in albums],
        role=ROLE_COVER,
    )
    artist_name = _effective_name(artist) or artist.name
    return MusicArtistDetailOut(
        id=artist.id,
        name=artist_name,
        image_path=resolve_art(
            db,
            entity_kind=ENTITY_ARTIST,
            entity_id=artist.id,
            role=ROLE_THUMB,
        ),
        album_count=len(albums),
        country=artist.country,
        artist_type=artist.artist_type,
        formed_year=artist.formed_year,
        disbanded_year=artist.disbanded_year,
        bio_source=artist.bio_source,
        metadata_synced_at=artist.metadata_synced_at,
        metadata_status=artist.metadata_status,
        bio_text=artist.bio_text,
        links=artist.links or [],
        sort_name=artist.sort_name,
        albums=[
            AlbumOut.model_validate({
                "id": a.id,
                "artist_id": a.artist_id,
                "artist_name": artist_name,
                "title": merge_overrides(a)["display_name"],
                "release_date": a.release_date,
                "cover_path": album_covers.get(a.id),
                "album_type": a.album_type,
                "metadata_synced_at": a.metadata_synced_at,
                "metadata_status": a.metadata_status,
            })
            for a in albums
        ],
    )


# ---------------------------------------------------------------------------
# Music videos
# ---------------------------------------------------------------------------
@router.get("/music-videos/artists", response_model=list[MusicVideoArtistOut])
def list_music_video_artists(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> list[MusicVideoArtistOut]:
    """Artists that have at least one MusicVideo row.

    Mirrors the /albums list shape: one card per artist with a count so
    the grid can show '3 videos' without a second request. Sorted by name
    so the UI is stable between refreshes.
    """
    skip_filter = _allow_pending(include_pending, user)
    stmt = (
        select(
            Artist,
            func.count(MusicVideo.id).label("video_count"),
        )
        .join(MusicVideo, MusicVideo.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(_sort_expr(Artist.name, Artist.sort_name))
    )
    if not skip_filter:
        stmt = stmt.where(
            exists(
                select(MediaFile.id)
                .where(MediaFile.kind == MediaKind.music_video)
                .where(MediaFile.ref_id == MusicVideo.id)
                .where(MediaFile.scan_state == ScanState.ready)
            )
        )
    rows = db.execute(stmt).all()
    artist_thumbs = resolve_art_batch(
        db,
        entity_kind=ENTITY_ARTIST,
        entity_ids=[ar.id for ar, _ in rows],
        role=ROLE_THUMB,
    )
    return [
        MusicVideoArtistOut(
            id=ar.id,
            name=_effective_name(ar) or ar.name,
            image_path=artist_thumbs.get(ar.id),
            video_count=int(video_count),
        )
        for ar, video_count in rows
    ]


@router.get(
    "/music-videos/artists/{artist_id}", response_model=MusicVideoArtistDetailOut,
)
def get_music_video_artist(
    artist_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> MusicVideoArtistDetailOut:
    """Artist detail plus the full list of their releases.

    Releases sort by `release_year DESC NULLS LAST`, tiebreaker on the
    article-stripped title (with sort_title as override). `video_count`
    and `disc_count` are aggregated server-side from children that have at
    least one ready MediaFile, so the tile counts match the playable set.
    """
    skip_filter = _allow_pending(include_pending, user)
    artist = db.get(Artist, artist_id)
    if artist is None:
        raise HTTPException(status_code=404, detail="artist_not_found")

    # Aggregated per-release video and disc counts. We join through
    # music_videos to media_files so a release with rows but no ready
    # files surfaces as zero — and gets filtered out below for non-admin.
    video_count_col = func.count(
        func.distinct(
            case((MediaFile.scan_state == ScanState.ready, MusicVideo.id))
        )
    )
    disc_count_col = func.coalesce(func.max(MusicVideo.disc_number), 1)
    releases_stmt = (
        select(
            MusicVideoRelease,
            video_count_col.label("video_count"),
            disc_count_col.label("disc_count"),
        )
        .outerjoin(MusicVideo, MusicVideo.release_id == MusicVideoRelease.id)
        .outerjoin(
            MediaFile,
            (MediaFile.kind == MediaKind.music_video)
            & (MediaFile.ref_id == MusicVideo.id),
        )
        .where(MusicVideoRelease.artist_id == artist.id)
        .group_by(MusicVideoRelease.id)
        .order_by(
            func.coalesce(
                MusicVideoRelease.sort_year, MusicVideoRelease.release_year,
            ).desc().nulls_last(),
            _sort_expr(MusicVideoRelease.title, MusicVideoRelease.sort_title),
        )
    )
    rows = list(db.execute(releases_stmt).all())
    if not skip_filter:
        rows = [r for r in rows if int(r.video_count) > 0]
    if not skip_filter and not rows:
        raise HTTPException(status_code=404, detail="artist_not_found")

    return MusicVideoArtistDetailOut(
        id=artist.id,
        name=_effective_name(artist) or artist.name,
        image_path=resolve_art(
            db,
            entity_kind=ENTITY_ARTIST,
            entity_id=artist.id,
            role=ROLE_THUMB,
        ),
        video_count=sum(int(r.video_count) for r in rows),
        releases=[
            MusicVideoReleaseOut(
                id=r.MusicVideoRelease.id,
                artist_id=r.MusicVideoRelease.artist_id,
                title=merge_overrides(r.MusicVideoRelease)["display_name"],
                release_year=merge_overrides(r.MusicVideoRelease)["year"],
                release_date=r.MusicVideoRelease.release_date,
                cover_path=r.MusicVideoRelease.cover_path,
                video_count=int(r.video_count),
                disc_count=int(r.disc_count),
                sort_title=r.MusicVideoRelease.sort_title,
                sort_year=r.MusicVideoRelease.sort_year,
            )
            for r in rows
        ],
    )


@router.get(
    "/music-videos/releases/{release_id}",
    response_model=MusicVideoReleaseDetailOut,
)
def get_music_video_release(
    release_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_pending: bool = Query(False),
) -> MusicVideoReleaseDetailOut:
    """One release with its ordered videos.

    Videos sort by `(disc_number ASC, track_number ASC NULLS LAST,
    article-stripped title)`. Each video carries its primary ready
    MediaFile id so the tile click can deep-link straight to
    /watch/<media_file_id>.
    """
    skip_filter = _allow_pending(include_pending, user)
    release = db.get(MusicVideoRelease, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release_not_found")

    artist = db.get(Artist, release.artist_id)
    if artist is None:
        raise HTTPException(status_code=404, detail="release_not_found")

    videos_stmt = (
        select(MusicVideo)
        .where(MusicVideo.release_id == release.id)
        .order_by(
            MusicVideo.disc_number.asc(),
            MusicVideo.track_number.asc().nulls_last(),
            _sort_expr(MusicVideo.title, MusicVideo.sort_title),
        )
    )
    if not skip_filter:
        videos_stmt = videos_stmt.where(
            _ready_files_subq(MusicVideo.id, MediaKind.music_video),
        )
    videos = list(db.scalars(videos_stmt))
    if not skip_filter and not videos:
        raise HTTPException(status_code=404, detail="release_not_found")

    files_by_ref = _files_by_ref(
        db, MediaKind.music_video, [mv.id for mv in videos],
    )
    disc_count = max((mv.disc_number for mv in videos), default=1)

    release_eff = merge_overrides(release)
    return MusicVideoReleaseDetailOut(
        id=release.id,
        artist_id=release.artist_id,
        artist_name=_effective_name(artist) or artist.name,
        title=release_eff["display_name"],
        release_year=release_eff["year"],
        release_date=release.release_date,
        cover_path=release.cover_path,
        video_count=len(videos),
        disc_count=disc_count,
        sort_title=release.sort_title,
        sort_year=release.sort_year,
        videos=[
            MusicVideoOut(
                id=mv.id,
                release_id=mv.release_id,
                title=mv.title,
                year=mv.year,
                disc_number=mv.disc_number,
                track_number=mv.track_number,
                thumb_path=resolve_art(
                    db,
                    entity_kind=ENTITY_MUSIC_VIDEO,
                    entity_id=mv.id,
                    role=ROLE_THUMB,
                ),
                media_file_id=_first_playable(files_by_ref.get(mv.id, [])),
                duration_sec=_first_duration(files_by_ref.get(mv.id, [])),
            )
            for mv in videos
        ],
    )


@router.get(
    "/music-videos/recent", response_model=list[RecentMusicVideoOut],
)
def list_recent_music_videos(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(12, ge=1, le=100),
) -> list[RecentMusicVideoOut]:
    """Most-recently-added music videos as a flat list.

    Source is `media_files.created_at DESC` filtered to
    `kind=music_video, scan_state=ready`. Tiles render at 16:9 on the home
    rail and link straight to `/watch/<media_file_id>` for one-click play.
    Includes `release_id`, `release_title`, and `artist_name` so the
    subtitle can render context without another call.
    """
    stmt = (
        select(MediaFile, MusicVideo, MusicVideoRelease, Artist)
        .join(MusicVideo, MusicVideo.id == MediaFile.ref_id)
        .join(MusicVideoRelease, MusicVideoRelease.id == MusicVideo.release_id)
        .join(Artist, Artist.id == MusicVideoRelease.artist_id)
        .where(MediaFile.kind == MediaKind.music_video)
        .where(MediaFile.scan_state == ScanState.ready)
        .order_by(MediaFile.created_at.desc())
        .limit(limit)
    )
    rows = list(db.execute(stmt).all())
    music_video_thumbs = resolve_art_batch(
        db,
        entity_kind=ENTITY_MUSIC_VIDEO,
        entity_ids=[mv.id for _, mv, _, _ in rows],
        role=ROLE_THUMB,
    )
    return [
        RecentMusicVideoOut(
            id=mv.id,
            title=mv.title,
            artist_name=ar.name,
            release_id=rel.id,
            release_title=rel.title,
            thumb_path=music_video_thumbs.get(mv.id),
            media_file_id=mf.id,
            added_at=mf.created_at,
        )
        for mf, mv, rel, ar in rows
    ]


def _first_playable(files: list[MediaFile]) -> Optional[uuid.UUID]:
    """Pick the first file in `ready` state. Returns None if none exist
    (either no file on disk, or only missing/error rows)."""
    for mf in files:
        if mf.scan_state == ScanState.ready:
            return mf.id
    return None


def _first_duration(files: list[MediaFile]) -> Optional[int]:
    for mf in files:
        if mf.scan_state == ScanState.ready and mf.duration_sec:
            return mf.duration_sec
    return None


# ---------------------------------------------------------------------------
# Recently added
# ---------------------------------------------------------------------------
@router.get("/recent", response_model=list[RecentItemOut])
def list_recent(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
) -> list[RecentItemOut]:
    """Most recently added playable items across movies, TV, and music.

    Ordering is by `media_files.created_at DESC` which is the moment
    F7FIVE0 first saw the file. We collapse multiple files for the same
    parent (e.g., a series with a new episode added minutes later) to a
    single row so the home shelf doesn't repeat posters. Only `ready`
    files count; a movie that hasn't probed yet is not "watchable" and
    would give the user a 409 when they click it.
    """
    # Pull 5x the ask so we have room to dedupe by (kind, parent_id).
    overshoot = min(limit * 5, 500)
    files = list(db.scalars(
        select(MediaFile)
        .where(MediaFile.scan_state == ScanState.ready)
        .order_by(MediaFile.created_at.desc())
        .limit(overshoot)
    ))

    # Group files so we have one row per parent. Keep the earliest-seen
    # added_at per parent (first in the desc scan = most recent).
    seen_parents: dict[tuple[MediaKind, uuid.UUID], MediaFile] = {}
    movie_ids: set[uuid.UUID] = set()
    episode_ids: set[uuid.UUID] = set()
    track_ids: set[uuid.UUID] = set()
    order: list[tuple[MediaKind, uuid.UUID]] = []

    for mf in files:
        if mf.kind == MediaKind.music_video:
            continue  # out of scope for this row in Phase 3
        parent_key: tuple[MediaKind, uuid.UUID]
        if mf.kind == MediaKind.movie:
            parent_key = (MediaKind.movie, mf.ref_id)
            movie_ids.add(mf.ref_id)
        elif mf.kind == MediaKind.episode:
            # Dedup at the episode level; we resolve to series after lookup.
            parent_key = (MediaKind.episode, mf.ref_id)
            episode_ids.add(mf.ref_id)
        else:  # track
            parent_key = (MediaKind.track, mf.ref_id)
            track_ids.add(mf.ref_id)
        if parent_key in seen_parents:
            continue
        seen_parents[parent_key] = mf
        order.append(parent_key)
        if len(order) >= limit * 2:
            break  # plenty of headroom once we resolve parents

    # Batch-load the parents we need. Episodes collapse to series below,
    # so a single series with three fresh episodes still shows up once.
    movies = {
        m.id: m for m in db.scalars(
            select(Movie).where(Movie.id.in_(movie_ids))
        )
    } if movie_ids else {}
    episodes = {
        e.id: e for e in db.scalars(
            select(Episode).where(Episode.id.in_(episode_ids))
        )
    } if episode_ids else {}
    series_ids = {e.series_id for e in episodes.values()}
    series_map = {
        s.id: s for s in db.scalars(
            select(Series).where(Series.id.in_(series_ids))
        )
    } if series_ids else {}
    tracks = {
        t.id: t for t in db.scalars(
            select(Track).where(Track.id.in_(track_ids))
        )
    } if track_ids else {}
    album_ids = {t.album_id for t in tracks.values()}
    albums = {
        a.id: a for a in db.scalars(
            select(Album).where(Album.id.in_(album_ids))
        )
    } if album_ids else {}
    artist_ids = {a.artist_id for a in albums.values()}
    artists = {
        ar.id: ar for ar in db.scalars(
            select(Artist).where(Artist.id.in_(artist_ids))
        )
    } if artist_ids else {}

    movie_posters = resolve_art_batch(
        db, entity_kind=ENTITY_MOVIE, entity_ids=movies.keys(), role=ROLE_POSTER,
    )
    series_posters = resolve_art_batch(
        db, entity_kind=ENTITY_SERIES, entity_ids=series_map.keys(),
        role=ROLE_POSTER,
    )
    album_covers = resolve_art_batch(
        db, entity_kind=ENTITY_ALBUM, entity_ids=albums.keys(), role=ROLE_COVER,
    )

    out: list[RecentItemOut] = []
    series_seen: set[uuid.UUID] = set()
    album_seen: set[uuid.UUID] = set()

    for kind, ref_id in order:
        mf = seen_parents[(kind, ref_id)]
        added_at = mf.created_at
        if kind == MediaKind.movie:
            m = movies.get(ref_id)
            if m is None:
                continue
            m_eff = merge_overrides(m)
            out.append(RecentItemOut(
                kind="movie", id=m.id, title=m_eff["display_name"],
                year=m_eff["year"],
                poster_path=movie_posters.get(m.id), added_at=added_at,
            ))
        elif kind == MediaKind.episode:
            ep = episodes.get(ref_id)
            if ep is None:
                continue
            if ep.series_id in series_seen:
                continue
            series_seen.add(ep.series_id)
            s = series_map.get(ep.series_id)
            if s is None:
                continue
            label = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
            subtitle = f"{label} - {ep.title}" if ep.title else label
            out.append(RecentItemOut(
                kind="series", id=s.id, title=_effective_name(s) or s.title,
                subtitle=subtitle, poster_path=series_posters.get(s.id),
                added_at=added_at,
            ))
        elif kind == MediaKind.track:
            t = tracks.get(ref_id)
            if t is None:
                continue
            if t.album_id in album_seen:
                continue
            album_seen.add(t.album_id)
            a = albums.get(t.album_id)
            if a is None:
                continue
            ar = artists.get(a.artist_id)
            subtitle = _effective_name(ar) if ar else None
            out.append(RecentItemOut(
                kind="album", id=a.id, title=_effective_name(a) or a.title,
                subtitle=subtitle, poster_path=album_covers.get(a.id),
                added_at=added_at,
            ))
        if len(out) >= limit:
            break

    return out


# ---------------------------------------------------------------------------
# New-arrivals badge + intro/credits markers (ux-extras)
# ---------------------------------------------------------------------------
@router.get("/recent/badge", response_model=NewArrivalsBadgeOut)
def recent_badge(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NewArrivalsBadgeOut:
    """Count of ready media added since the caller last loaded home.

    A null last_seen_home_at (never stamped) falls back to account
    creation. The frontend caps the display at 99+."""
    since = user.last_seen_home_at or user.created_at
    count = db.scalar(
        select(func.count())
        .select_from(MediaFile)
        .where(MediaFile.scan_state == ScanState.ready)
        .where(MediaFile.created_at > since)
    )
    return NewArrivalsBadgeOut(count=int(count or 0))


@router.post("/recent/seen", status_code=204)
def recent_seen(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Stamp the caller's last home-page visit to now, zeroing the badge."""
    user.last_seen_home_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/markers/{media_file_id}", response_model=list[MediaMarkerOut])
def get_markers(
    media_file_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MediaMarkerOut]:
    """Intro/credits markers for one media file, earliest first. Empty list
    when none are detected; the player just renders no skip button."""
    rows = db.scalars(
        select(MediaMarker)
        .where(MediaMarker.media_file_id == media_file_id)
        .order_by(MediaMarker.start_sec)
    ).all()
    return [MediaMarkerOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@router.get("/search", response_model=list[SearchResultOut])
def search_library(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=200),
    kind: Optional[str] = Query(default=None, pattern="^(movie|series|album)$"),
    limit: int = Query(25, ge=1, le=100),
    include_pending: bool = Query(False),
    deep: bool = Query(False),
) -> list[SearchResultOut]:
    """Case-insensitive substring search across movies, series, and albums.

    For Phase 4 we only index the parent titles (plus artist name for
    albums). Episode and track titles are intentionally excluded: most
    users expect "breaking bad" to return the series, not every
    individual episode that happens to contain those words.

    The query is split on whitespace and each term must appear somewhere
    in the candidate's searchable text, so "star trek picard" still hits
    even though the official title has punctuation between tokens. The
    result set is capped server-side; the client renders a tidy list and
    does not need to paginate.
    """
    terms = [t for t in q.strip().split() if t]
    if not terms:
        return []

    skip_filter = _allow_pending(include_pending, user)

    def like_clauses(column):
        return [
            func.lower(column).like(f"%{_like_escape(t.lower())}%", escape="\\")
            for t in terms
        ]

    out: list[SearchResultOut] = []

    if kind in (None, "movie"):
        clauses = like_clauses(Movie.title)
        movies_stmt = (
            select(Movie)
            .where(*clauses)
            .order_by(Movie.title)
            .limit(limit)
        )
        if not skip_filter:
            movies_stmt = movies_stmt.where(
                _ready_files_subq(Movie.id, MediaKind.movie),
            )
        movies = list(db.scalars(movies_stmt))
        movie_posters = resolve_art_batch(
            db, entity_kind=ENTITY_MOVIE,
            entity_ids=[m.id for m in movies], role=ROLE_POSTER,
        )
        for m in movies:
            m_eff = merge_overrides(m)
            out.append(SearchResultOut(
                kind="movie", id=m.id, title=m_eff["display_name"],
                year=m_eff["year"],
                poster_path=movie_posters.get(m.id),
            ))

    if kind in (None, "series"):
        clauses = like_clauses(Series.title)
        series_stmt = (
            select(Series)
            .where(*clauses)
            .order_by(Series.title)
            .limit(limit)
        )
        if not skip_filter:
            series_stmt = series_stmt.where(
                exists(
                    select(Episode.id)
                    .join(
                        MediaFile,
                        (MediaFile.kind == MediaKind.episode)
                        & (MediaFile.ref_id == Episode.id),
                    )
                    .where(Episode.series_id == Series.id)
                    .where(MediaFile.scan_state == ScanState.ready)
                )
            )
        series_rows = list(db.scalars(series_stmt))
        series_posters = resolve_art_batch(
            db, entity_kind=ENTITY_SERIES,
            entity_ids=[s.id for s in series_rows], role=ROLE_POSTER,
        )
        for s in series_rows:
            out.append(SearchResultOut(
                kind="series", id=s.id, title=_effective_name(s) or s.title,
                poster_path=series_posters.get(s.id),
            ))

    if kind in (None, "album"):
        # Albums match on either album title or artist name. We join
        # Artist so we can surface "artist_name" as the subtitle and so
        # a search for "miles davis" still returns his albums. Every
        # query term must appear in the combined "title + artist" text.
        combined = func.lower(Album.title + " " + Artist.name)
        stmt = (
            select(Album, Artist)
            .join(Artist, Artist.id == Album.artist_id)
        )
        for t in terms:
            stmt = stmt.where(
                combined.like(f"%{_like_escape(t.lower())}%", escape="\\")
            )
        if not skip_filter:
            stmt = stmt.where(
                exists(
                    select(Track.id)
                    .join(
                        MediaFile,
                        (MediaFile.kind == MediaKind.track)
                        & (MediaFile.ref_id == Track.id),
                    )
                    .where(Track.album_id == Album.id)
                    .where(MediaFile.scan_state == ScanState.ready)
                )
            )
        rows = list(db.execute(stmt.order_by(Album.title).limit(limit)))
        album_covers = resolve_art_batch(
            db, entity_kind=ENTITY_ALBUM,
            entity_ids=[album.id for album, _ in rows], role=ROLE_COVER,
        )
        for album, artist in rows:
            out.append(SearchResultOut(
                kind="album", id=album.id,
                title=_effective_name(album) or album.title,
                subtitle=_effective_name(artist) if artist else None,
                poster_path=album_covers.get(album.id),
            ))

    if deep:
        # Episode and Track titles are excluded from the default search
        # (users expect "breaking bad" to return the series, not every
        # episode). The deep flag widens to them but surfaces the PARENT
        # series / album so the result card still links somewhere
        # navigable. Dedup against parents already in `out`.
        seen_series = {r.id for r in out if r.kind == "series"}
        seen_albums = {r.id for r in out if r.kind == "album"}

        if kind in (None, "series"):
            ep_stmt = (
                select(Episode, Series)
                .join(Series, Series.id == Episode.series_id)
                .where(*like_clauses(Episode.title))
                .order_by(Episode.title)
                .limit(limit)
            )
            if not skip_filter:
                ep_stmt = ep_stmt.where(
                    _ready_files_subq(Episode.id, MediaKind.episode),
                )
            for ep, s in db.execute(ep_stmt).all():
                if s.id in seen_series:
                    continue
                seen_series.add(s.id)
                label = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
                subtitle = f"{label} - {ep.title}" if ep.title else label
                out.append(SearchResultOut(
                    kind="series", id=s.id,
                    title=_effective_name(s) or s.title,
                    subtitle=subtitle,
                    poster_path=resolve_art(
                        db, entity_kind=ENTITY_SERIES, entity_id=s.id,
                        role=ROLE_POSTER,
                    ),
                ))

        if kind in (None, "album"):
            tr_stmt = (
                select(Track, Album)
                .join(Album, Album.id == Track.album_id)
                .where(*like_clauses(Track.title))
                .order_by(Track.title)
                .limit(limit)
            )
            if not skip_filter:
                tr_stmt = tr_stmt.where(
                    _ready_files_subq(Track.id, MediaKind.track),
                )
            for tr, a in db.execute(tr_stmt).all():
                if a.id in seen_albums:
                    continue
                seen_albums.add(a.id)
                out.append(SearchResultOut(
                    kind="album", id=a.id,
                    title=_effective_name(a) or a.title,
                    subtitle=tr.title,
                    poster_path=resolve_art(
                        db, entity_kind=ENTITY_ALBUM, entity_id=a.id,
                        role=ROLE_COVER,
                    ),
                ))

    # Cap the combined result. Without a kind filter this returns up to
    # 3*limit (more with deep on); trim it so the client gets a predictable
    # page size.
    return out[:limit]


# ---------------------------------------------------------------------------
# Watch progress
# ---------------------------------------------------------------------------
@router.put("/progress/{media_file_id}", response_model=ProgressOut)
def upsert_progress(
    media_file_id: uuid.UUID,
    body: ProgressUpsertRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProgressOut:
    """Heartbeat write from the player. Idempotent upsert keyed on (user, file).

    The player calls this every ~10 seconds during playback and once more
    on unmount. We stamp completed_at when position crosses the 90% mark so
    the Continue Watching shelf can exclude it. We do NOT clear
    completed_at if the user rewinds back below the threshold; once watched,
    stays watched until explicitly toggled.
    """
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="file_not_found")

    # Prefer the explicit duration passed by the player (it knows what it's
    # actually playing), fall back to the probe value, then to any prior
    # recorded duration.
    row = db.get(WatchProgress, (user.id, media_file_id))
    duration = body.duration_sec or mf.duration_sec or (row.duration_sec if row else None)
    position = min(body.position_sec, duration) if duration else body.position_sec

    completed_at: Optional[datetime] = row.completed_at if row else None
    if duration and position >= int(duration * COMPLETED_FRACTION):
        completed_at = completed_at or datetime.now(timezone.utc)

    if row is None:
        row = WatchProgress(
            user_id=user.id,
            media_file_id=media_file_id,
            position_sec=position,
            duration_sec=duration,
            completed_at=completed_at,
        )
        db.add(row)
    else:
        row.position_sec = position
        row.duration_sec = duration
        row.completed_at = completed_at
    try:
        db.commit()
    except IntegrityError:
        # Two first heartbeats for the same (user, file) raced: the other one
        # inserted the row between our read and our insert. Fall back to an
        # update of the row that now exists instead of a 500.
        db.rollback()
        row = db.get(WatchProgress, (user.id, media_file_id))
        if row is None:
            raise
        row.position_sec = position
        row.duration_sec = duration
        row.completed_at = row.completed_at or completed_at
        db.commit()
    db.refresh(row)
    return ProgressOut.model_validate(row)


@router.get("/progress/{media_file_id}", response_model=Optional[ProgressOut])
def get_progress(
    media_file_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Optional[ProgressOut]:
    """Read progress for one file. Returns null body when none recorded."""
    row = db.get(WatchProgress, (user.id, media_file_id))
    if row is None:
        return None
    return ProgressOut.model_validate(row)


@router.delete("/progress/{media_file_id}", status_code=204)
def clear_progress(
    media_file_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Remove progress. Used by 'Mark unwatched' in the UI.

    Delete rather than zero so the file falls off Continue Watching cleanly.
    """
    row = db.get(WatchProgress, (user.id, media_file_id))
    if row is not None:
        db.delete(row)
        db.commit()


@router.post("/progress/{media_file_id}/mark-watched", response_model=ProgressOut)
def mark_watched(
    media_file_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProgressOut:
    """Stamp completed_at without requiring the client to know duration.

    Used by the "Mark as watched" menu action. We pin position to duration
    (or the last known position if duration is unknown) so Continue Watching
    filters it out cleanly, and stamp completed_at to now.
    """
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="file_not_found")

    row = db.get(WatchProgress, (user.id, media_file_id))
    duration = mf.duration_sec or (row.duration_sec if row else None)
    position = duration if duration else (row.position_sec if row else 0)
    now = datetime.now(timezone.utc)

    if row is None:
        row = WatchProgress(
            user_id=user.id,
            media_file_id=media_file_id,
            position_sec=position,
            duration_sec=duration,
            completed_at=now,
        )
        db.add(row)
    else:
        row.position_sec = position
        row.duration_sec = duration
        row.completed_at = now
    db.commit()
    db.refresh(row)
    return ProgressOut.model_validate(row)


@router.get("/progress", response_model=list[ProgressOut])
def list_progress(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ProgressOut]:
    """Return the user's full WatchProgress as a flat list.

    Used by the frontend to decorate library grids and detail pages with
    watched/in-progress indicators in one call. For a 5-user instance the
    row count stays small; if this ever shows strain we can add a
    `since=<timestamp>` query param and have the client cache locally.
    """
    rows = list(db.scalars(
        select(WatchProgress).where(WatchProgress.user_id == user.id)
    ))
    return [ProgressOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Track plays (audio play log)
# ---------------------------------------------------------------------------
@router.post("/track-plays", response_model=TrackPlayOut, status_code=201)
def create_track_play(
    body: TrackPlayCreateRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TrackPlayOut:
    """Record a finished or skipped-with-progress audio play.

    The MiniPlayer calls this on the `<audio>` `ended` event and on a
    skip after at least 30 seconds of playback. user_id comes from the
    JWT; extra fields (including a stray user_id) are rejected so a
    client can't write rows for someone else.
    """
    track = db.get(Track, body.track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="track_not_found")

    row = TrackPlay(
        user_id=user.id,
        track_id=body.track_id,
        ms_played=body.ms_played,
        completed=body.completed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return TrackPlayOut.model_validate(row)


# ---------------------------------------------------------------------------
# Continue watching
# ---------------------------------------------------------------------------
@router.get("/continue-watching", response_model=list[ContinueWatchingItemOut])
def list_continue_watching(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(12, ge=1, le=50),
) -> list[ContinueWatchingItemOut]:
    """Unfinished items ordered by most-recent-update.

    Same parent collapse as /recent: one row per movie, series, album.
    We pull 5x and dedupe so a series with two in-progress episodes still
    shows up once (most recent episode wins). Completed rows are filtered
    server-side. Rows under MIN_PROGRESS_SECONDS are hidden so a misclick
    doesn't pollute the shelf.
    """
    overshoot = min(limit * 5, 250)
    rows = list(db.scalars(
        select(WatchProgress)
        .where(
            WatchProgress.user_id == user.id,
            WatchProgress.completed_at.is_(None),
            WatchProgress.position_sec >= MIN_PROGRESS_SECONDS,
        )
        .order_by(WatchProgress.updated_at.desc())
        .limit(overshoot)
    ))
    if not rows:
        return []

    files = {
        mf.id: mf for mf in db.scalars(
            select(MediaFile).where(
                MediaFile.id.in_(r.media_file_id for r in rows)
            )
        )
    }

    # Batch-load the parents we'll need.
    movie_ids: set[uuid.UUID] = set()
    episode_ids: set[uuid.UUID] = set()
    track_ids: set[uuid.UUID] = set()
    music_video_ids: set[uuid.UUID] = set()
    for mf in files.values():
        if mf.kind == MediaKind.movie:
            movie_ids.add(mf.ref_id)
        elif mf.kind == MediaKind.episode:
            episode_ids.add(mf.ref_id)
        elif mf.kind == MediaKind.track:
            track_ids.add(mf.ref_id)
        elif mf.kind == MediaKind.music_video:
            music_video_ids.add(mf.ref_id)

    movies = {
        m.id: m for m in db.scalars(
            select(Movie).where(Movie.id.in_(movie_ids))
        )
    } if movie_ids else {}
    episodes = {
        e.id: e for e in db.scalars(
            select(Episode).where(Episode.id.in_(episode_ids))
        )
    } if episode_ids else {}
    series_ids = {e.series_id for e in episodes.values()}
    series_map = {
        s.id: s for s in db.scalars(
            select(Series).where(Series.id.in_(series_ids))
        )
    } if series_ids else {}
    tracks = {
        t.id: t for t in db.scalars(
            select(Track).where(Track.id.in_(track_ids))
        )
    } if track_ids else {}
    album_ids = {t.album_id for t in tracks.values()}
    albums = {
        a.id: a for a in db.scalars(
            select(Album).where(Album.id.in_(album_ids))
        )
    } if album_ids else {}
    music_videos = {
        mv.id: mv for mv in db.scalars(
            select(MusicVideo).where(MusicVideo.id.in_(music_video_ids))
        )
    } if music_video_ids else {}
    release_ids = {mv.release_id for mv in music_videos.values()}
    releases = {
        rel.id: rel for rel in db.scalars(
            select(MusicVideoRelease)
            .where(MusicVideoRelease.id.in_(release_ids))
        )
    } if release_ids else {}
    artist_ids = (
        {a.artist_id for a in albums.values()}
        | {rel.artist_id for rel in releases.values()}
    )
    artists = {
        ar.id: ar for ar in db.scalars(
            select(Artist).where(Artist.id.in_(artist_ids))
        )
    } if artist_ids else {}

    cw_movie_posters = resolve_art_batch(
        db, entity_kind=ENTITY_MOVIE, entity_ids=movies.keys(), role=ROLE_POSTER,
    )
    cw_series_posters = resolve_art_batch(
        db, entity_kind=ENTITY_SERIES, entity_ids=series_map.keys(),
        role=ROLE_POSTER,
    )
    cw_album_covers = resolve_art_batch(
        db, entity_kind=ENTITY_ALBUM, entity_ids=albums.keys(), role=ROLE_COVER,
    )

    out: list[ContinueWatchingItemOut] = []
    seen_movie: set[uuid.UUID] = set()
    seen_series: set[uuid.UUID] = set()
    seen_album: set[uuid.UUID] = set()
    seen_release: set[uuid.UUID] = set()

    for r in rows:
        mf = files.get(r.media_file_id)
        if mf is None:
            continue
        if mf.kind == MediaKind.movie:
            if mf.ref_id in seen_movie:
                continue
            m = movies.get(mf.ref_id)
            if m is None:
                continue
            seen_movie.add(mf.ref_id)
            m_eff = merge_overrides(m)
            out.append(ContinueWatchingItemOut(
                kind="movie", id=m.id, media_file_id=mf.id,
                title=m_eff["display_name"], year=m_eff["year"],
                poster_path=cw_movie_posters.get(m.id),
                position_sec=r.position_sec, duration_sec=r.duration_sec,
                updated_at=r.updated_at,
            ))
        elif mf.kind == MediaKind.episode:
            ep = episodes.get(mf.ref_id)
            if ep is None:
                continue
            if ep.series_id in seen_series:
                continue
            s = series_map.get(ep.series_id)
            if s is None:
                continue
            seen_series.add(ep.series_id)
            label = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
            subtitle = f"{label} - {ep.title}" if ep.title else label
            out.append(ContinueWatchingItemOut(
                kind="series", id=s.id, media_file_id=mf.id,
                title=_effective_name(s) or s.title, subtitle=subtitle,
                poster_path=cw_series_posters.get(s.id),
                position_sec=r.position_sec, duration_sec=r.duration_sec,
                updated_at=r.updated_at,
            ))
        elif mf.kind == MediaKind.track:
            t = tracks.get(mf.ref_id)
            if t is None:
                continue
            if t.album_id in seen_album:
                continue
            a = albums.get(t.album_id)
            if a is None:
                continue
            seen_album.add(t.album_id)
            ar = artists.get(a.artist_id)
            out.append(ContinueWatchingItemOut(
                kind="album", id=a.id, media_file_id=mf.id,
                title=_effective_name(a) or a.title,
                subtitle=_effective_name(ar) if ar else None,
                poster_path=cw_album_covers.get(a.id),
                position_sec=r.position_sec, duration_sec=r.duration_sec,
                updated_at=r.updated_at,
            ))
        elif mf.kind == MediaKind.music_video:
            mv = music_videos.get(mf.ref_id)
            if mv is None:
                continue
            # Collapse at the release level so watching three videos out of
            # Substance produces one tile pointing at the release page.
            if mv.release_id in seen_release:
                continue
            rel = releases.get(mv.release_id)
            if rel is None:
                continue
            seen_release.add(mv.release_id)
            ar = artists.get(rel.artist_id)
            rel_eff = merge_overrides(rel)
            out.append(ContinueWatchingItemOut(
                kind="music_video_release",
                id=rel.id,
                media_file_id=mf.id,
                title=rel_eff["display_name"],
                subtitle=_effective_name(ar) if ar else None,
                year=rel_eff["year"],
                poster_path=rel.cover_path,
                position_sec=r.position_sec, duration_sec=r.duration_sec,
                updated_at=r.updated_at,
            ))
        if len(out) >= limit:
            break
    return out


@router.get("/on-deck", response_model=list[OnDeckItemOut])
def list_on_deck(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=50),
) -> list[OnDeckItemOut]:
    """Next episode to watch per started series, most recently active first.

    Unlike /continue-watching (which only lists unfinished files), this rolls
    forward past a finished episode to the next one, like Plex's On Deck.
    """
    from app.services.on_deck import EpisodeRef, ProgressRef, next_episode

    ep_rows = list(db.execute(
        select(Episode.series_id, func.max(WatchProgress.updated_at))
        .join(MediaFile, MediaFile.ref_id == Episode.id)
        .join(WatchProgress, WatchProgress.media_file_id == MediaFile.id)
        .where(
            WatchProgress.user_id == user.id,
            MediaFile.kind == MediaKind.episode,
        )
        .group_by(Episode.series_id)
        .order_by(func.max(WatchProgress.updated_at).desc())
        .limit(limit * 2)
    ))
    if not ep_rows:
        return []
    series_ids = [r[0] for r in ep_rows]
    last_active = {r[0]: r[1] for r in ep_rows}

    series_map = {
        s.id: s for s in db.scalars(select(Series).where(Series.id.in_(series_ids)))
    }
    episodes = list(db.scalars(select(Episode).where(Episode.series_id.in_(series_ids))))
    ep_ids = [e.id for e in episodes]
    files = list(db.scalars(
        select(MediaFile).where(
            MediaFile.kind == MediaKind.episode,
            MediaFile.ref_id.in_(ep_ids),
            MediaFile.scan_state == ScanState.ready,
        )
    )) if ep_ids else []
    file_for_ep: dict[uuid.UUID, MediaFile] = {}
    for mf in files:
        file_for_ep.setdefault(mf.ref_id, mf)
    progress_rows = list(db.scalars(
        select(WatchProgress).where(
            WatchProgress.user_id == user.id,
            WatchProgress.media_file_id.in_([mf.id for mf in files]),
        )
    )) if files else []
    progress = {
        p.media_file_id: ProgressRef(position_sec=p.position_sec or 0,
                                     completed=p.completed_at is not None)
        for p in progress_rows
    }
    progress_row = {p.media_file_id: p for p in progress_rows}

    by_series: dict[uuid.UUID, list[EpisodeRef]] = {}
    ep_by_id = {e.id: e for e in episodes}
    for e in episodes:
        mf = file_for_ep.get(e.id)
        by_series.setdefault(e.series_id, []).append(EpisodeRef(
            episode_id=e.id, season_number=e.season_number,
            episode_number=e.episode_number,
            media_file_id=mf.id if mf is not None else None,
        ))

    posters = resolve_art_batch(
        db, entity_kind=ENTITY_SERIES, entity_ids=series_map.keys(), role=ROLE_POSTER,
    )
    out: list[OnDeckItemOut] = []
    for sid in series_ids:
        s = series_map.get(sid)
        if s is None:
            continue
        pick = next_episode(by_series.get(sid, []), progress,
                            min_progress_sec=MIN_PROGRESS_SECONDS)
        if pick is None:
            continue
        ep = ep_by_id[pick.episode_id]
        mf = file_for_ep[ep.id]
        prow = progress_row.get(mf.id)
        in_progress = prow is not None and prow.completed_at is None
        label = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
        out.append(OnDeckItemOut(
            id=s.id, episode_id=ep.id, media_file_id=mf.id,
            title=_effective_name(s) or s.title,
            subtitle=f"{label} - {ep.title}" if ep.title else label,
            season_number=ep.season_number, episode_number=ep.episode_number,
            poster_path=posters.get(s.id),
            position_sec=prow.position_sec if in_progress else 0,
            duration_sec=(prow.duration_sec if prow is not None else None) or mf.duration_sec,
            updated_at=last_active[sid],
        ))
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Is a folder scan running? (any signed-in user: the empty library pages use it)
# ---------------------------------------------------------------------------
@router.get("/library/scan-state")
def library_scan_state(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Only whether a scan is running and when the last one finished. The
    counts and errors stay on the admin endpoint."""
    return scan_status.scan_state(db)


# ---------------------------------------------------------------------------
# Admin: force sync
# ---------------------------------------------------------------------------
@router.post("/sync/run", status_code=202)
def trigger_sync_now(
    _admin: Annotated[User, Depends(require_admin)],
) -> dict:
    """Fire a full *arr sync immediately. Returns 202; the job runs async."""
    scheduler.trigger_full_sync_now()
    return {"status": "enqueued"}


@router.post("/sync/music-videos", status_code=202)
def trigger_music_videos_scan(
    _admin: Annotated[User, Depends(require_admin)],
) -> dict:
    """Walk the music-videos NAS root and reconcile DB rows. Runs out of
    band on the scheduler's executor so the admin UI gets a 202 straight
    back. Progress shows up in logs; the UI polls list endpoints for the
    new rows."""
    scheduler.trigger_music_videos_scan_now()
    return {"status": "enqueued"}


@router.post("/series/{series_id}/rescan", status_code=202)
def rescan_series_folder(
    series_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Tell Sonarr to rescan this series' folder, then refresh our DB.

    Use when a file was dropped into the series folder outside Sonarr's
    import pipeline (manual download, different tool). Sonarr's
    RescanSeries command walks the folder and imports new episode files;
    the follow-up refresh_series pulls the updated state into F7FIVE0.

    Runs on the scheduler's executor; the endpoint returns 202 immediately.
    """
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="series_not_found")
    if series.sonarr_id is None:
        raise HTTPException(status_code=409, detail="series_not_linked_to_sonarr")
    scheduler.trigger_series_rescan_now(series.sonarr_id)
    return {"status": "enqueued", "sonarr_id": series.sonarr_id}
