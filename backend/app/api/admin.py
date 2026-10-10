"""Admin-only read endpoints for the operator panel.

Non-library admin surface: active transcode sessions and recent watch
history. User management and sync-trigger already live on the auth and
library routers respectively; see /api/auth/users and /api/library/sync/run.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import uuid

from fastapi import HTTPException

from app import scheduler
from app.api.deps import evict_session_cache, get_db, require_admin
from app.api.schemas import (
    AudioAnalysisProgressOut, AudioAnalysisStartOut,
    LibraryFolderOut, LibraryFoldersIn, LibraryFoldersLibraryOut, LibraryFoldersOut,
    MergeArtistIn, MergePreviewOut, MergeResultOut, UndoMergeResultOut,
    MetadataSettingsOut, NasCredentialIn, NasCredentialOut, NasSaveOut,
    ReminderOut, ReminderSnoozeIn, TmdbKeyCheckOut, TmdbKeyIn,
    TmdbKeyStatusOut, UpdateBadgeOut, UpdateRunOut, UpdatesOut,
    ActiveTranscodeOut, AdminSessionOut, AuthEventOut, MatchApply,
    MatchCandidate, MatchCandidatesOut, OverrideOut, OverrideUpdate,
    ServerHealthOut, SortOverrideOut, SortOverrideUpdate, WatchHistoryRowOut,
)
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import (
    Album, Artist, ArtistMerge, MusicVideo, MusicVideoRelease, Track,
)
from app.models.playback import WatchHistory
from app.models.transcode import TranscodeCache, TranscodeSession
from app.models.tv import Episode, Series
from app.models.user import AuthEvent, Session as UserSession, User
from app.services.arr._base import ArrClientError
from app.services.arr.lidarr import LidarrClient
from app.services.arr.radarr import RadarrClient
from app.services.arr.sonarr import SonarrClient
from app.config import settings
from app.services import (
    android_app, library_folders, nas_auth, reminders, remote_access as ra,
    scan_status, server_version, tmdb_key, updates,
)
from app.services import artist_merge
from app.services.metadata._base import ProviderError
from app.services.metadata.musicbrainz import MusicBrainzClient
from app.services.metadata.runner import (
    enrich_album, enrich_artist, enrich_movie, enrich_series,
)
from app.services.metadata.tmdb import TMDBClient

log = logging.getLogger("f7five0.admin.override")


router = APIRouter()


# ---------------------------------------------------------------------------
# Active transcode sessions
# ---------------------------------------------------------------------------
@router.get("/transcodes/active", response_model=list[ActiveTranscodeOut])
def active_transcodes(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ActiveTranscodeOut]:
    """Rows in transcode_sessions with no ended_at. One per live stream.

    Includes direct-play sessions (direct_play=True) because the session row
    is still the place the admin looks to see who's watching what. Sorted newest
    first so a 'someone just started streaming' event is easy to spot."""
    rows = list(
        db.scalars(
            select(TranscodeSession)
            .where(TranscodeSession.ended_at.is_(None))
            .order_by(TranscodeSession.started_at.desc())
        )
    )
    if not rows:
        return []

    user_ids = {r.user_id for r in rows}
    file_ids = {r.media_file_id for r in rows}
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))
    }
    files = {
        f.id: f for f in db.scalars(select(MediaFile).where(MediaFile.id.in_(file_ids)))
    }
    title_by_file = _titles_for_files(db, files.values())

    out: list[ActiveTranscodeOut] = []
    for r in rows:
        user = users.get(r.user_id)
        mf = files.get(r.media_file_id)
        out.append(
            ActiveTranscodeOut(
                id=r.id,
                user_id=r.user_id,
                user_display_name=user.display_name if user else "(unknown)",
                media_file_id=r.media_file_id,
                title=title_by_file.get(r.media_file_id) or (mf.path if mf else "(unknown)"),
                variant=r.variant,
                direct_play=r.direct_play,
                started_at=r.started_at,
                bytes_served=r.bytes_served,
                speed=r.speed,
                below_realtime_sec=r.below_realtime_sec,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Recent watch history
# ---------------------------------------------------------------------------
@router.get("/history/recent", response_model=list[WatchHistoryRowOut])
def recent_history(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=500),
) -> list[WatchHistoryRowOut]:
    """Most recent playback starts across all users. Read-only."""
    rows = list(
        db.scalars(
            select(WatchHistory)
            .order_by(WatchHistory.started_at.desc())
            .limit(limit)
        )
    )
    if not rows:
        return []

    user_ids = {r.user_id for r in rows}
    file_ids = {r.media_file_id for r in rows}
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))
    }
    files = {
        f.id: f for f in db.scalars(select(MediaFile).where(MediaFile.id.in_(file_ids)))
    }
    title_by_file = _titles_for_files(db, files.values())

    out: list[WatchHistoryRowOut] = []
    for r in rows:
        user = users.get(r.user_id)
        mf = files.get(r.media_file_id)
        out.append(
            WatchHistoryRowOut(
                id=r.id,
                user_id=r.user_id,
                user_display_name=user.display_name if user else "(unknown)",
                media_file_id=r.media_file_id,
                title=title_by_file.get(r.media_file_id) or (mf.path if mf else "(unknown)"),
                started_at=r.started_at,
                ended_at=r.ended_at,
                last_position_sec=r.last_position_sec,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Sessions: list + revoke
# ---------------------------------------------------------------------------
@router.get("/sessions", response_model=list[AdminSessionOut])
def list_sessions(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AdminSessionOut]:
    """Active (unrevoked, unexpired) sessions across all users.

    Newest activity first so a freshly-used device is easy to spot. Each
    row carries client_type and device_label so an admin can tell a PWA
    (10-year refresh) apart from a browser session and revoke it if a
    phone goes missing."""
    now = datetime.now(timezone.utc)
    rows = list(
        db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(
                UserSession.last_seen_at.desc().nulls_last(),
                UserSession.created_at.desc(),
            )
        ).all()
    )
    return [
        AdminSessionOut(
            id=s.id,
            user_id=s.user_id,
            username=u.username,
            display_name=u.display_name,
            device_label=s.device_label,
            client_type=s.client_type,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
        )
        for s, u in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Revoke one session by id. Idempotent on an already-revoked row;
    404 only when the id is unknown. The revoked session's access tokens
    stop working once the deps.current_user grace window elapses, and its
    refresh token can no longer rotate."""
    session = db.get(UserSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    # Drop any cached revocation state so the revoke takes effect now rather
    # than waiting out the deps micro-cache TTL.
    evict_session_cache(session_id)


# ---------------------------------------------------------------------------
# Auth events
# ---------------------------------------------------------------------------
@router.get("/auth-events", response_model=list[AuthEventOut])
def list_auth_events(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuthEventOut]:
    """Newest-first auth audit rows joined to usernames.

    The limit is clamped to 200 in code regardless of the query value so a
    caller can't pull the whole table. user_id is nullable (e.g. a failed
    login for an unknown username), so the join is an outer join and
    username comes back null for those rows."""
    capped = min(limit, 200)
    rows = list(
        db.execute(
            select(AuthEvent, User.username)
            .outerjoin(User, User.id == AuthEvent.user_id)
            .order_by(AuthEvent.at.desc())
            .limit(capped)
        ).all()
    )
    return [
        AuthEventOut(
            id=ev.id,
            user_id=ev.user_id,
            username=username,
            event=ev.event,
            ip=str(ev.ip) if ev.ip is not None else None,
            user_agent=ev.user_agent,
            at=ev.at,
        )
        for ev, username in rows
    ]


# ---------------------------------------------------------------------------
# Server health
# ---------------------------------------------------------------------------
def _disk_usage_safe(path: Path) -> shutil._ntuple_diskusage:
    """shutil.disk_usage against the nearest existing ancestor of `path`.

    The cache or art directory may not exist yet on a fresh box; walk up to
    a parent that does (ultimately the drive anchor) so the health card
    still reports the drive's free/total instead of erroring."""
    p = Path(path)
    while not p.exists():
        parent = p.parent
        if parent == p:
            break
        p = parent
    return shutil.disk_usage(str(p))


@router.get("/health", response_model=ServerHealthOut)
def server_health(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ServerHealthOut:
    """Operator health snapshot: transcode cache usage vs cap, disk free on
    the cache and art drives, count of open transcode sessions, and last
    sync time. Drive letters are read from settings at runtime. last_sync_at
    is null because no persistent sync bookkeeping exists yet."""
    cache_bytes = int(
        db.scalar(select(func.coalesce(func.sum(TranscodeCache.size_bytes), 0))) or 0
    )
    open_sessions = int(
        db.scalar(
            select(func.count())
            .select_from(TranscodeSession)
            .where(TranscodeSession.ended_at.is_(None))
        )
        or 0
    )
    cache_du = _disk_usage_safe(settings.transcode_cache_dir)
    art_du = _disk_usage_safe(settings.art_root)
    return ServerHealthOut(
        transcode_cache_bytes=cache_bytes,
        transcode_cache_max_bytes=settings.transcode_cache_max_gb * 1024 ** 3,
        cache_disk_free_bytes=cache_du.free,
        cache_disk_total_bytes=cache_du.total,
        art_disk_free_bytes=art_du.free,
        art_disk_total_bytes=art_du.total,
        open_transcode_sessions=open_sessions,
        last_sync_at=None,
    )


# ---------------------------------------------------------------------------
# Intro/credits marker analysis (ux-extras)
# ---------------------------------------------------------------------------
@router.post("/markers/analyze", status_code=202)
def analyze_markers(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    series_id: Optional[uuid.UUID] = Query(default=None),
    force: bool = Query(default=False),
) -> dict:
    """Kick off an intro/credits detection pass over episode files.

    Scope to one series with series_id, or omit to scan the whole TV
    library. The work runs out of band on the scheduler (one ffmpeg at a
    time); the response reports how many ready episode files are in scope so
    the admin knows roughly how long to wait. Files that already have markers
    are skipped unless force=true."""
    stmt = (
        select(func.count())
        .select_from(MediaFile)
        .where(MediaFile.kind == MediaKind.episode)
        .where(MediaFile.scan_state == ScanState.ready)
    )
    if series_id is not None:
        stmt = stmt.where(
            MediaFile.ref_id.in_(
                select(Episode.id).where(Episode.series_id == series_id)
            )
        )
    in_scope = int(db.scalar(stmt) or 0)
    scheduler.trigger_marker_analysis_now(series_id=series_id, force=force)
    return {
        "status": "enqueued",
        "episode_files_in_scope": in_scope,
        "series_id": str(series_id) if series_id else None,
        "force": force,
    }


# ---------------------------------------------------------------------------
# Audio analysis (smart-audio backfill)
# ---------------------------------------------------------------------------
@router.get("/audio/progress", response_model=AudioAnalysisProgressOut)
def audio_analysis_progress(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AudioAnalysisProgressOut:
    """How far the automatic audio-analysis backfill has got.

    Loudness leveling, the waveform scrubber, and similar-track radio all read
    `track_audio_analysis` / `track_similarity`, which the scheduler fills one
    track at a time. The admin panel polls this to show `analyzed / total`."""
    from app.services import audio_analysis as aa
    prog = aa.analysis_progress(db)
    return AudioAnalysisProgressOut(
        analyzed=prog["analyzed"],
        total=prog["total"],
        pending=max(0, prog["total"] - prog["analyzed"]),
    )


@router.post("/audio/analyze", response_model=AudioAnalysisStartOut, status_code=202)
def analyze_audio_now(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AudioAnalysisStartOut:
    """Start (or re-arm) the automatic audio-analysis walk now.

    Backs the 'Analyze music now' admin action. The work runs out of band on
    the scheduler, one track at a time, using the same engine as the
    analyze-audio CLI. Already-analyzed tracks are skipped, so this is safe to
    click repeatedly; it just fills whatever is still pending."""
    from app.services import audio_analysis as aa
    prog = aa.analysis_progress(db)
    pending = max(0, prog["total"] - prog["analyzed"])
    scheduler.trigger_audio_analysis_now()
    return AudioAnalysisStartOut(
        status="enqueued", pending=pending, total=prog["total"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _titles_for_files(db: Session, files) -> dict:
    """Best-effort human title for a set of media files, indexed by file id.

    MediaFile is polymorphic (kind + ref_id). We bucket refs by kind, fetch
    parent rows, then map back. Unmatched files simply aren't in the output
    map; callers fall back to the file path."""
    files = list(files)
    if not files:
        return {}

    movie_ids: set = set()
    episode_ids: set = set()
    track_ids: set = set()
    for f in files:
        if f.kind == MediaKind.movie:
            movie_ids.add(f.ref_id)
        elif f.kind == MediaKind.episode:
            episode_ids.add(f.ref_id)
        elif f.kind == MediaKind.track:
            track_ids.add(f.ref_id)

    movies = (
        {m.id: m for m in db.scalars(select(Movie).where(Movie.id.in_(movie_ids)))}
        if movie_ids else {}
    )
    episodes = (
        {e.id: e for e in db.scalars(select(Episode).where(Episode.id.in_(episode_ids)))}
        if episode_ids else {}
    )
    series_ids = {e.series_id for e in episodes.values()}
    series_rows = (
        {s.id: s for s in db.scalars(select(Series).where(Series.id.in_(series_ids)))}
        if series_ids else {}
    )
    tracks = (
        {t.id: t for t in db.scalars(select(Track).where(Track.id.in_(track_ids)))}
        if track_ids else {}
    )
    album_ids = {t.album_id for t in tracks.values() if t.album_id}
    albums = (
        {a.id: a for a in db.scalars(select(Album).where(Album.id.in_(album_ids)))}
        if album_ids else {}
    )

    titles: dict = {}
    for f in files:
        if f.kind == MediaKind.movie and f.ref_id in movies:
            titles[f.id] = movies[f.ref_id].title
        elif f.kind == MediaKind.episode and f.ref_id in episodes:
            ep = episodes[f.ref_id]
            series_title = (
                series_rows[ep.series_id].title
                if ep.series_id in series_rows else "Unknown series"
            )
            titles[f.id] = (
                f"{series_title} S{ep.season_number:02d}E{ep.episode_number:02d}"
            )
        elif f.kind == MediaKind.track and f.ref_id in tracks:
            track = tracks[f.ref_id]
            album = albums.get(track.album_id) if track.album_id else None
            if album:
                titles[f.id] = f"{album.title} / {track.title}"
            else:
                titles[f.id] = track.title
    return titles

# ---------------------------------------------------------------------------
# Sort overrides (admin)
# ---------------------------------------------------------------------------
_SORT_KIND_MAP = {
    "movie":               (Movie,             "sort_title"),
    "series":              (Series,            "sort_title"),
    "artist":              (Artist,            "sort_name"),
    "music_video_release": (MusicVideoRelease, "sort_title"),
    "music_video":         (MusicVideo,        "sort_title"),
}


@router.patch("/sort/{kind}/{entity_id}", response_model=SortOverrideOut)
def patch_sort_override(
    kind: str,
    entity_id: uuid.UUID,
    body: SortOverrideUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> SortOverrideOut:
    """Set or clear the sort override on a movie / series / artist row.

    Empty-string values are normalized to null so the UI can reliably
    clear an override by submitting an empty input. Returns the saved
    value so the caller can sync local state.
    """
    info = _SORT_KIND_MAP.get(kind)
    if info is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "invalid_kind: must be one of "
                "movie|series|artist|music_video_release|music_video"
            ),
        )
    model_cls, column_name = info

    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")

    raw = body.value
    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            raw = None
    setattr(row, column_name, raw)
    db.commit()
    return SortOverrideOut(value=getattr(row, column_name))


# ---------------------------------------------------------------------------
# Unified overrides + Fix Match + Refresh
# ---------------------------------------------------------------------------
# One PATCH per kind sets every override the modal can write. Two GET/POST
# pairs run Fix Match search and apply. One POST re-pulls canonical
# metadata from the currently attached external id. Every endpoint is
# admin-gated.

# Kind name -> ORM model. The same kind names show up in OverrideUpdate /
# match endpoints; one map keeps them in sync. `tracks` lives here even
# though Fix Match for tracks returns 422 -- a track is matched implicitly
# via its parent album's MBID.
_OVERRIDE_KIND_MAP: dict[str, type] = {
    "movie": Movie,
    "series": Series,
    "artist": Artist,
    "album": Album,
    "track": Track,
    "music_video_release": MusicVideoRelease,
}

# Sort column name per kind; `Artist.sort_name` is the historical odd one
# out. Kept consistent with _SORT_KIND_MAP above.
_SORT_COLUMN_MAP: dict[str, str] = {
    "movie": "sort_title",
    "series": "sort_title",
    "artist": "sort_name",
    "album": "sort_title",
    "track": "sort_title",
    "music_video_release": "sort_title",
}


def _name_field(kind: str) -> str:
    """Wire-level display field for a kind: `name` for artist, `title` else."""
    return "name" if kind == "artist" else "title"


def _canonical_dict(kind: str, row: Any) -> dict:
    """Fields the modal renders alongside the override values.

    Surfaces only what the Edit Overrides modal actually displays so the
    response payload stays slim. Year sources vary by kind: `year` on
    Movie, `first_aired.year` on Series, `release_year` on
    MusicVideoRelease, `release_date.year` on Album.
    """
    out: dict[str, Any] = {}
    name_field = _name_field(kind)
    out[name_field] = getattr(row, name_field, None)

    out["tagline"] = getattr(row, "tagline", None)

    year: Optional[int] = getattr(row, "year", None)
    if year is None:
        first_aired = getattr(row, "first_aired", None)
        if first_aired is not None:
            year = first_aired.year
    if year is None:
        year = getattr(row, "release_year", None)
    if year is None:
        release_date = getattr(row, "release_date", None)
        if release_date is not None:
            year = release_date.year
    out["year"] = year

    out["runtime_min"] = getattr(row, "runtime_min", None)

    rating = getattr(row, "tmdb_rating", None)
    if rating is None:
        rating = getattr(row, "mb_rating", None)
    out["rating"] = rating

    out["poster_path"] = getattr(row, "poster_path", None) or getattr(
        row, "cover_path", None,
    ) or getattr(row, "image_path", None)
    out["backdrop_path"] = getattr(row, "backdrop_path", None)
    return out


def _external_id(kind: str, row: Any) -> Optional[dict]:
    """Source-of-truth pointer for Refresh and Fix Match.

    Movies: TMDB id. Series: TVDB id (TMDB id as fallback). Music kinds:
    MBID. Returns None when the entity has no external id (which is what
    Refresh checks for its 422 branch).
    """
    if kind == "movie":
        if row.tmdb_id is not None:
            return {"source": "tmdb", "id": str(row.tmdb_id)}
        return None
    if kind == "series":
        if row.tvdb_id is not None:
            return {"source": "tvdb", "id": str(row.tvdb_id)}
        if row.tmdb_id is not None:
            return {"source": "tmdb", "id": str(row.tmdb_id)}
        return None
    if kind in ("artist", "album", "track", "music_video_release"):
        mbid = getattr(row, "mbid", None)
        if mbid:
            return {"source": "musicbrainz", "id": mbid}
        return None
    return None


def _override_out(kind: str, row: Any) -> OverrideOut:
    sort_col = _SORT_COLUMN_MAP[kind]
    return OverrideOut(
        kind=kind,
        entity_id=row.id,
        canonical=_canonical_dict(kind, row),
        overrides=dict(row.overrides or {}),
        sort_title=getattr(row, sort_col, None),
        external_id=_external_id(kind, row),
    )


_RUNTIME_FIELDS_REQUIRE_KIND = {"movie", "series"}


@router.get("/override/{kind}/{entity_id}", response_model=OverrideOut)
def get_override(
    kind: str,
    entity_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> OverrideOut:
    """Read the current effective override view for one entity.

    Lets the Edit Overrides modal pre-populate inputs without exposing
    the raw `overrides` JSONB on every detail-fetch response.
    """
    model_cls = _OVERRIDE_KIND_MAP.get(kind)
    if model_cls is None:
        raise HTTPException(status_code=422, detail="invalid_kind")
    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")
    return _override_out(kind, row)


@router.patch("/override/{kind}/{entity_id}", response_model=OverrideOut)
def patch_override(
    kind: str,
    entity_id: uuid.UUID,
    body: OverrideUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> OverrideOut:
    """Apply a partial override patch to an entity.

    Body fields use Pydantic's three-state convention:
      - omitted          -> untouched
      - explicit None    -> override cleared
      - non-null value   -> override set

    `sort_title` writes to the entity's existing sort column (Artist uses
    `sort_name`); every other field writes into the `overrides` JSONB
    blob. The response carries the full effective state so the caller can
    sync local UI without a follow-up GET.
    """
    model_cls = _OVERRIDE_KIND_MAP.get(kind)
    if model_cls is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "invalid_kind: must be one of "
                "movie|series|artist|album|track|music_video_release"
            ),
        )

    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")

    fields_set = body.model_fields_set
    sort_col = _SORT_COLUMN_MAP[kind]

    # SQLAlchemy treats the JSONB column as immutable on assignment; copy,
    # mutate, reassign so it actually flushes.
    overrides = dict(row.overrides or {})

    if "runtime_min" in fields_set and kind not in _RUNTIME_FIELDS_REQUIRE_KIND:
        raise HTTPException(
            status_code=422,
            detail=f"runtime_min not applicable to kind '{kind}'",
        )

    JSONB_FIELDS = ("display_name", "tagline", "year", "runtime_min", "rating")

    for field in JSONB_FIELDS:
        if field not in fields_set:
            continue
        value = getattr(body, field)
        if value is None:
            overrides.pop(field, None)
        else:
            overrides[field] = value

    if "sort_title" in fields_set:
        raw = body.sort_title
        if isinstance(raw, str):
            raw = raw.strip() or None
        setattr(row, sort_col, raw)

    row.overrides = overrides
    db.commit()
    db.refresh(row)
    return _override_out(kind, row)


# ---------------------------------------------------------------------------
# Fix Match: candidates + apply
# ---------------------------------------------------------------------------
def _arr_image_url(images: Optional[list], cover_type: str = "poster") -> Optional[str]:
    if not images:
        return None
    for img in images:
        if (img or {}).get("coverType") == cover_type:
            url = img.get("remoteUrl") or img.get("url")
            if url:
                return url
    # Fall back to whichever image came back.
    for img in images:
        url = (img or {}).get("remoteUrl") or (img or {}).get("url")
        if url:
            return url
    return None


def _normalize_radarr_movie(payload: dict) -> Optional[MatchCandidate]:
    tmdb_id = payload.get("tmdbId")
    if not tmdb_id:
        return None
    return MatchCandidate(
        source="tmdb",
        ref=str(tmdb_id),
        label=payload.get("title") or payload.get("originalTitle") or "Untitled",
        year=payload.get("year"),
        image_url=_arr_image_url(payload.get("images"), "poster"),
        summary=payload.get("overview"),
    )


def _normalize_sonarr_series(payload: dict) -> Optional[MatchCandidate]:
    tvdb_id = payload.get("tvdbId")
    tmdb_id = payload.get("tmdbId")
    # Prefer tvdb because Sonarr keys series by it; fall back to tmdb.
    if tvdb_id:
        return MatchCandidate(
            source="tvdb",
            ref=str(tvdb_id),
            label=payload.get("title") or "Untitled",
            year=payload.get("year"),
            image_url=_arr_image_url(payload.get("images"), "poster"),
            summary=payload.get("overview"),
        )
    if tmdb_id:
        return MatchCandidate(
            source="tmdb",
            ref=str(tmdb_id),
            label=payload.get("title") or "Untitled",
            year=payload.get("year"),
            image_url=_arr_image_url(payload.get("images"), "poster"),
            summary=payload.get("overview"),
        )
    return None


def _normalize_lidarr_artist(payload: dict) -> Optional[MatchCandidate]:
    mbid = payload.get("foreignArtistId")
    if not mbid:
        return None
    return MatchCandidate(
        source="musicbrainz",
        ref=str(mbid),
        label=payload.get("artistName") or "Untitled",
        year=None,
        image_url=_arr_image_url(payload.get("images"), "poster"),
        summary=payload.get("overview") or payload.get("disambiguation"),
    )


def _normalize_lidarr_album(payload: dict) -> Optional[MatchCandidate]:
    mbid = payload.get("foreignAlbumId")
    if not mbid:
        return None
    release_date = payload.get("releaseDate")
    year: Optional[int] = None
    if isinstance(release_date, str) and len(release_date) >= 4:
        try:
            year = int(release_date[:4])
        except ValueError:
            year = None
    return MatchCandidate(
        source="musicbrainz",
        ref=str(mbid),
        label=payload.get("title") or "Untitled",
        year=year,
        image_url=_arr_image_url(payload.get("images"), "cover"),
        summary=payload.get("overview") or payload.get("disambiguation"),
    )


def _normalize_mb_artist(payload: dict) -> Optional[MatchCandidate]:
    mbid = payload.get("id")
    if not mbid:
        return None
    disamb = payload.get("disambiguation")
    country = payload.get("country")
    bits = [b for b in (payload.get("type"), country) if b]
    summary = payload.get("disambiguation") or (", ".join(bits) or None)
    label = payload.get("name") or "Untitled"
    if disamb:
        label = f"{label} ({disamb})"
    return MatchCandidate(
        source="musicbrainz",
        ref=str(mbid),
        label=label,
        year=None,
        image_url=None,
        summary=summary,
    )


def _normalize_mb_release_group(payload: dict) -> Optional[MatchCandidate]:
    mbid = payload.get("id")
    if not mbid:
        return None
    credits = payload.get("artist-credit") or []
    artist = ""
    if credits and isinstance(credits[0], dict):
        artist = (credits[0].get("artist") or {}).get("name") or credits[0].get("name") or ""
    title = payload.get("title") or "Untitled"
    label = f"{artist} - {title}" if artist else title
    year: Optional[int] = None
    first = payload.get("first-release-date")
    if isinstance(first, str) and len(first) >= 4 and first[:4].isdigit():
        year = int(first[:4])
    return MatchCandidate(
        source="musicbrainz",
        ref=str(mbid),
        label=label,
        year=year,
        image_url=None,
        summary=payload.get("primary-type") or None,
    )


def _normalize_tmdb_movie(payload: dict) -> Optional[MatchCandidate]:
    tmdb_id = payload.get("id")
    if not tmdb_id:
        return None
    year: Optional[int] = None
    date = payload.get("release_date")
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        year = int(date[:4])
    poster = payload.get("poster_path")
    image = f"https://image.tmdb.org/t/p/w342{poster}" if poster else None
    return MatchCandidate(
        source="tmdb",
        ref=str(tmdb_id),
        label=payload.get("title") or payload.get("original_title") or "Untitled",
        year=year,
        image_url=image,
        summary=payload.get("overview") or None,
    )


def _normalize_tmdb_series(payload: dict) -> Optional[MatchCandidate]:
    tmdb_id = payload.get("id")
    if not tmdb_id:
        return None
    year: Optional[int] = None
    date = payload.get("first_air_date")
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        year = int(date[:4])
    poster = payload.get("poster_path")
    image = f"https://image.tmdb.org/t/p/w342{poster}" if poster else None
    return MatchCandidate(
        source="tmdb",
        ref=str(tmdb_id),
        label=payload.get("name") or payload.get("original_name") or "Untitled",
        year=year,
        image_url=image,
        summary=payload.get("overview") or None,
    )


def _dedupe_candidates(items: list[MatchCandidate]) -> list[MatchCandidate]:
    """De-dupe by (source, ref). First occurrence wins, so a direct source
    (TMDB / MusicBrainz) sits above the same id surfaced by an *arr."""
    seen: set[tuple[str, str]] = set()
    out: list[MatchCandidate] = []
    for c in items:
        key = (c.source, c.ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# Friendly callout lines for a source that would help but is not set up.
_MATCH_TMDB_MISSING = (
    "Movies and TV search TMDB. Add a TMDB key in Admin to search here."
)
_MATCH_ARR_MISSING = {
    "lidarr": "Connect Lidarr to also search your Lidarr library.",
    "radarr": "Connect Radarr to also search your Radarr library.",
    "sonarr": "Connect Sonarr to also search your Sonarr library.",
}


def _run_source(
    notes: list[str],
    display: str,
    fn,
    out: list[MatchCandidate],
) -> None:
    """Run one search source. On any failure, record a friendly note and
    keep going so one dead source never drops the others' results."""
    try:
        for c in fn():
            if c is not None:
                out.append(c)
    except (ArrClientError, ProviderError) as exc:
        log.warning("match source %s failed: %s", display, exc)
        notes.append(f"{display} did not answer.")
    except Exception as exc:  # noqa: BLE001
        log.warning("match source %s errored: %s", display, exc)
        notes.append(f"{display} did not answer.")


@router.get(
    "/match/{kind}/{entity_id}/candidates", response_model=MatchCandidatesOut,
)
def match_candidates(
    kind: str,
    entity_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=200),
) -> MatchCandidatesOut:
    """Search every configured source for the kind and normalize results.

    *arr is optional: artists and albums search MusicBrainz (no key),
    movies and series search TMDB when a key is set, and each *arr adds its
    own library when its key is set. Each source is best-effort: a dead or
    unconfigured source becomes a friendly note, never a raw error, and the
    other sources still return their results. De-duped by (source, ref).

    Tracks return 422 -- a track is matched implicitly through its parent
    album's MBID.
    """
    model_cls = _OVERRIDE_KIND_MAP.get(kind)
    if model_cls is None:
        raise HTTPException(status_code=422, detail="invalid_kind")
    if kind == "track":
        raise HTTPException(
            status_code=422,
            detail="track_not_supported: tracks match implicitly via album MBID",
        )
    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")

    out: list[MatchCandidate] = []
    notes: list[str] = []

    if kind == "movie":
        if tmdb_key.get():
            _run_source(
                notes, "TMDB",
                lambda: _tmdb_movie_search(q), out,
            )
        else:
            notes.append(_MATCH_TMDB_MISSING)
        if settings.radarr_api_key:
            _run_source(notes, "Radarr", lambda: _radarr_search(q), out)
        else:
            notes.append(_MATCH_ARR_MISSING["radarr"])
    elif kind == "series":
        if tmdb_key.get():
            _run_source(notes, "TMDB", lambda: _tmdb_series_search(q), out)
        else:
            notes.append(_MATCH_TMDB_MISSING)
        if settings.sonarr_api_key:
            _run_source(notes, "Sonarr", lambda: _sonarr_search(q), out)
        else:
            notes.append(_MATCH_ARR_MISSING["sonarr"])
    elif kind == "artist":
        _run_source(notes, "MusicBrainz", lambda: _mb_artist_search(q), out)
        if settings.lidarr_api_key:
            _run_source(notes, "Lidarr", lambda: _lidarr_artist_search(q), out)
        else:
            notes.append(_MATCH_ARR_MISSING["lidarr"])
    elif kind in ("album", "music_video_release"):
        _run_source(notes, "MusicBrainz", lambda: _mb_release_group_search(q), out)
        if settings.lidarr_api_key:
            _run_source(notes, "Lidarr", lambda: _lidarr_album_search(q), out)
        else:
            notes.append(_MATCH_ARR_MISSING["lidarr"])
    else:
        raise HTTPException(status_code=422, detail="invalid_kind")

    return MatchCandidatesOut(candidates=_dedupe_candidates(out), notes=notes)


# ---------------------------------------------------------------------------
# Fix Match source adapters. Each returns a list of MatchCandidate (or None
# entries, dropped by _run_source) and raises on a hard failure the runner
# turns into a friendly note.
# ---------------------------------------------------------------------------
def _tmdb_movie_search(q: str) -> list[Optional[MatchCandidate]]:
    with TMDBClient() as cli:
        raw = cli.search_many("movie", q)
    return [_normalize_tmdb_movie(p) for p in raw or []]


def _tmdb_series_search(q: str) -> list[Optional[MatchCandidate]]:
    with TMDBClient() as cli:
        raw = cli.search_many("tv", q)
    return [_normalize_tmdb_series(p) for p in raw or []]


def _mb_artist_search(q: str) -> list[Optional[MatchCandidate]]:
    with MusicBrainzClient() as mb:
        raw = mb.search_artists(q)
    return [_normalize_mb_artist(p) for p in raw or []]


def _mb_release_group_search(q: str) -> list[Optional[MatchCandidate]]:
    with MusicBrainzClient() as mb:
        raw = mb.search_release_groups(q)
    return [_normalize_mb_release_group(p) for p in raw or []]


def _radarr_search(q: str) -> list[Optional[MatchCandidate]]:
    with RadarrClient(settings.radarr_url, settings.radarr_api_key) as rc:
        raw = rc.movie_lookup(q)
    return [_normalize_radarr_movie(p) for p in raw or []]


def _sonarr_search(q: str) -> list[Optional[MatchCandidate]]:
    with SonarrClient(settings.sonarr_url, settings.sonarr_api_key) as sc:
        raw = sc.series_lookup(q)
    return [_normalize_sonarr_series(p) for p in raw or []]


def _lidarr_artist_search(q: str) -> list[Optional[MatchCandidate]]:
    with LidarrClient(settings.lidarr_url, settings.lidarr_api_key) as lc:
        raw = lc.artist_lookup(q)
    return [_normalize_lidarr_artist(p) for p in raw or []]


def _lidarr_album_search(q: str) -> list[Optional[MatchCandidate]]:
    with LidarrClient(settings.lidarr_url, settings.lidarr_api_key) as lc:
        raw = lc.album_lookup(q)
    return [_normalize_lidarr_album(p) for p in raw or []]


@router.post("/match/{kind}/{entity_id}", response_model=OverrideOut)
def apply_match(
    kind: str,
    entity_id: uuid.UUID,
    body: MatchApply,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> OverrideOut:
    """Re-attach the entity to a different external record.

    Steps: (1) write the new external id onto the entity row, (2)
    synchronously refresh canonical metadata from the new source, (3)
    return the freshened OverrideOut. Existing manual overrides on the
    entity are not touched -- only canonical fields refresh.
    """
    model_cls = _OVERRIDE_KIND_MAP.get(kind)
    if model_cls is None:
        raise HTTPException(status_code=422, detail="invalid_kind")
    if kind == "track":
        raise HTTPException(
            status_code=422,
            detail="track_not_supported",
        )
    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")

    source = body.source
    ref = body.ref

    # Write new external id and trigger the canonical refresh path that
    # matches the entity kind. Series do not yet have an enrich function,
    # so the new id lands on the row but the next *arr sync is what
    # repopulates Sonarr-driven canonical fields.
    if kind == "movie":
        if source != "tmdb":
            raise HTTPException(status_code=422, detail="source_must_be_tmdb")
        try:
            row.tmdb_id = int(ref)
        except ValueError:
            raise HTTPException(status_code=422, detail="ref_not_int")
        db.commit()
        enrich_movie(db, row.id, force=True)
    elif kind == "series":
        if source == "tvdb":
            try:
                row.tvdb_id = int(ref)
            except ValueError:
                raise HTTPException(status_code=422, detail="ref_not_int")
        elif source == "tmdb":
            try:
                row.tmdb_id = int(ref)
            except ValueError:
                raise HTTPException(status_code=422, detail="ref_not_int")
        else:
            raise HTTPException(status_code=422, detail="source_must_be_tvdb_or_tmdb")
        db.commit()
        # With a TMDB id and a key, pull canonical fields and art now so the
        # match is useful without Sonarr. A TVDB-only match (no TMDB id)
        # still waits for the next *arr sync; enrich_series no-ops on it.
        if source == "tmdb":
            enrich_series(db, row.id, force=True)
    elif kind == "artist":
        if source != "musicbrainz":
            raise HTTPException(status_code=422, detail="source_must_be_musicbrainz")
        row.mbid = ref
        db.commit()
        enrich_artist(db, row.id, force=True)
    elif kind == "album":
        if source != "musicbrainz":
            raise HTTPException(status_code=422, detail="source_must_be_musicbrainz")
        row.mbid = ref
        db.commit()
        enrich_album(db, row.id, force=True)
    elif kind == "music_video_release":
        if source != "musicbrainz":
            raise HTTPException(status_code=422, detail="source_must_be_musicbrainz")
        row.mbid = ref
        db.commit()
        # MusicVideoRelease has no MB-driven canonical columns today, so
        # there is nothing to enrich. The mbid pin is the whole apply.
    else:
        raise HTTPException(status_code=422, detail="invalid_kind")

    db.refresh(row)
    return _override_out(kind, row)


@router.post("/refresh/{kind}/{entity_id}", response_model=OverrideOut)
def refresh_metadata(
    kind: str,
    entity_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> OverrideOut:
    """Re-pull canonical metadata from the currently attached external id.

    422 when the entity has no external id (Refresh has nothing to do).
    Reuses the same enrich path Fix Match calls so behavior is consistent
    between the two paths.
    """
    model_cls = _OVERRIDE_KIND_MAP.get(kind)
    if model_cls is None:
        raise HTTPException(status_code=422, detail="invalid_kind")
    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")

    ext = _external_id(kind, row)
    if ext is None:
        raise HTTPException(
            status_code=422,
            detail="no_external_id: nothing to refresh",
        )

    if kind == "movie":
        enrich_movie(db, row.id, force=True)
    elif kind == "artist":
        enrich_artist(db, row.id, force=True)
    elif kind == "album":
        enrich_album(db, row.id, force=True)
    elif kind == "series":
        # TMDB-backed when a tmdb_id is attached; no-ops on a TVDB-only
        # series, which the *arr sync still owns.
        enrich_series(db, row.id, force=True)
    elif kind in ("track", "music_video_release"):
        # No synchronous enrich path; the *arr sync owns these surfaces.
        pass
    db.refresh(row)
    return _override_out(kind, row)


# ---------------------------------------------------------------------------
# Merge artists (admin only)
# ---------------------------------------------------------------------------
# An admin folds a collaboration-credit artist (for example "2Pac Featuring KC
# And Jojo") into the main artist. The albums and tracks move to the target, the
# source row goes away, and a durable alias is saved so the next folder scan or
# Lidarr sync does not recreate the source. Undo reverses it from a merge-record.
@router.get(
    "/artists/{source_id}/merge-preview", response_model=MergePreviewOut,
)
def merge_preview(
    source_id: uuid.UUID,
    target_id: Annotated[uuid.UUID, Query()],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MergePreviewOut:
    """How many albums and tracks a merge would move, so the confirm dialog can
    name it. 422 if source and target are the same artist."""
    if source_id == target_id:
        raise HTTPException(status_code=422, detail="cannot_merge_into_self")
    source = db.get(Artist, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source_not_found")
    target = db.get(Artist, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target_not_found")
    counts = artist_merge.preview(db, source)
    return MergePreviewOut(
        source_id=source.id, source_name=source.name,
        target_id=target.id, target_name=target.name,
        albums=counts["albums"], tracks=counts["tracks"],
    )


@router.get("/artists/{target_id}/merges")
def list_artist_merges(
    target_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict]:
    """Merges that folded another artist into this one and can still be undone.
    Lets the artist page offer "Undo merge" for each source that was merged in."""
    rows = db.scalars(
        select(ArtistMerge)
        .where(
            ArtistMerge.target_artist_id == target_id,
            ArtistMerge.undone_at.is_(None),
        )
        .order_by(ArtistMerge.created_at.desc())
    ).all()
    return [
        {
            "merge_id": str(r.id),
            "source_name": r.source_name,
            "albums": len(r.moved_album_ids or []),
        }
        for r in rows
    ]


@router.post("/artists/{source_id}/merge", response_model=MergeResultOut)
def merge_artist(
    source_id: uuid.UUID,
    body: MergeArtistIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MergeResultOut:
    """Merge the source artist into the target. Admin only."""
    if source_id == body.target_id:
        raise HTTPException(status_code=422, detail="cannot_merge_into_self")
    source = db.get(Artist, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source_not_found")
    target = db.get(Artist, body.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target_not_found")
    counts = artist_merge.preview(db, source)
    try:
        record = artist_merge.merge(db, source, target)
    except artist_merge.MergeError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return MergeResultOut(
        merge_id=record.id, target_id=target.id, target_name=target.name,
        albums_moved=counts["albums"], tracks_moved=counts["tracks"],
    )


@router.post(
    "/artists/merges/{merge_id}/undo", response_model=UndoMergeResultOut,
)
def undo_merge(
    merge_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> UndoMergeResultOut:
    """Undo a merge: remove its alias and restore the source artist with the
    albums and tracks that moved. Admin only."""
    record = db.get(ArtistMerge, merge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="merge_not_found")
    try:
        restored = artist_merge.undo(db, record)
    except artist_merge.MergeError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return UndoMergeResultOut(
        restored_artist_id=restored.id,
        restored_artist_name=restored.name,
        albums_restored=len(record.moved_album_ids or []),
    )


# ---------------------------------------------------------------------------
# Library folders: one or more source folders per library
# ---------------------------------------------------------------------------
def _library_folders_out(db: Session) -> LibraryFoldersOut:
    current = library_folders.all_folders(db)
    return LibraryFoldersOut(
        source=library_folders.source(db),
        libraries=[
            LibraryFoldersLibraryOut(
                kind=kind,
                label=library_folders.LABELS[kind],
                folders=[
                    LibraryFolderOut(
                        path=st.path, reachable=st.reachable,
                        reason=st.reason, signed_in_as=st.signed_in_as,
                    )
                    for st in (library_folders.status(p, db) for p in current[kind])
                ],
                arr_managed=library_folders.arr_managed(kind),
            )
            for kind in library_folders.KINDS
        ],
    )


@router.get("/library-folders", response_model=LibraryFoldersOut)
def get_library_folders(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> LibraryFoldersOut:
    """Each library's source folders, and whether the server can open them
    (as the account the F7FIVE0 services run under)."""
    return _library_folders_out(db)


@router.put("/library-folders", response_model=LibraryFoldersOut)
def put_library_folders(
    body: LibraryFoldersIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> LibraryFoldersOut:
    """Replace every library's folders, then start a folder scan. Folders the
    server can't open are still saved (a NAS may be asleep); the response
    flags them. Items from a removed folder leave the library (their files
    are marked missing); nothing is deleted and adding it back restores them."""
    unknown = set(body.folders) - set(library_folders.KINDS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown library: {', '.join(sorted(unknown))}")
    try:
        library_folders.save(db, body.folders)
    except library_folders.FolderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    log.info("library folders saved: %s", library_folders.all_folders(db))
    scheduler.trigger_folder_scan_now()
    return _library_folders_out(db)


@router.get("/library/scan")
def get_library_scan(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """The folder scan's state: running or idle, which library it is on, counts
    per library, when the last scan finished, and the last error."""
    return scan_status.read(db)


@router.post("/library/scan", status_code=202)
def start_library_scan(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Scan the library folders now. 409 while a scan is already running. The
    scan itself runs on the scheduler; poll GET /library/scan to watch it."""
    if not scan_status.begin(db):
        raise HTTPException(status_code=409, detail="scan_running")
    db.commit()
    try:
        scheduler.trigger_folder_scan_now()
    except Exception as exc:
        log.exception("could not queue the folder scan")
        scan_status.finish(db, "The scan could not be started.")
        db.commit()
        raise HTTPException(status_code=500, detail="scan_not_started") from exc
    return scan_status.read(db)


# ---------------------------------------------------------------------------
# NAS sign-in: a Windows sign-in per server, so LocalSystem can read a share
# ---------------------------------------------------------------------------
def _audit_event(db: Session, user_id: uuid.UUID, event: str, request: Request) -> None:
    """Append an auth-audit row for a sensitive admin action (a NAS sign-in
    change, an update). A password is never a parameter here, so it cannot
    land in the audit trail."""
    ip = getattr(request.state, "client_ip", None)
    ua = request.headers.get("user-agent")
    db.add(AuthEvent(
        user_id=user_id,
        event=event,
        ip=ip if ip and ip != "unknown" else None,
        user_agent=ua[:512] if ua else None,
        at=datetime.now(timezone.utc),
    ))


@router.get("/nas-credentials", response_model=list[NasCredentialOut])
def list_nas_credentials(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[NasCredentialOut]:
    """Every saved NAS sign-in, as server + username. Never returns a secret."""
    return [NasCredentialOut(**row) for row in nas_auth.list_servers(db)]


@router.put("/nas-credentials/{server}", response_model=NasSaveOut)
def put_nas_credential(
    server: str,
    body: NasCredentialIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> NasSaveOut:
    """Save (or change) the sign-in for a NAS server, reconnect its shares, and
    report the per-share connect status. The password is encrypted with DPAPI
    and never stored, logged, or returned. Accepts `user`, `DOMAIN\\user`, or
    `user@domain`."""
    if not nas_auth.available():
        raise HTTPException(status_code=501, detail="nas_sign_in_windows_only")
    result = nas_auth.save(db, server, body.username, body.password)
    _audit_event(db, _admin.id, "nas_sign_in_set", request)
    db.commit()
    log.info("nas sign-in saved for server %s as %s", result["server"], result["username"])
    return NasSaveOut(**result)


@router.delete("/nas-credentials/{server}", response_model=list[NasCredentialOut])
def delete_nas_credential(
    server: str,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> list[NasCredentialOut]:
    """Remove a server's sign-in and cancel its share connections."""
    if not nas_auth.available():
        raise HTTPException(status_code=501, detail="nas_sign_in_windows_only")
    nas_auth.remove(db, server)
    _audit_event(db, _admin.id, "nas_sign_in_removed", request)
    db.commit()
    log.info("nas sign-in removed for server %s", server.strip().lstrip("\\").lower())
    return [NasCredentialOut(**row) for row in nas_auth.list_servers(db)]


# ---------------------------------------------------------------------------
# Updates: check GitHub, update from a release, or upload a Setup
# ---------------------------------------------------------------------------
def get_update_helper() -> ra.Helper:
    return updates.get_helper()


# Refusals come back as the error code in `detail`; the admin page words them.
_UPDATE_STATUS = {
    "admin_password_required": 403, "admin_password_incorrect": 403, "too_many_attempts": 429,
    "untrusted_setup": 403, "update_running": 409, "no_update": 409, "not_newer": 409,
    "no_checksums": 409, "no_setup": 409, "too_large": 413, "not_an_exe": 400, "no_version": 400,
    "host_not_allowed": 400, "release_unreachable": 503, "helper_unavailable": 503, "helper_failed": 503,
}


def _update_http(exc: "updates.UpdateError") -> HTTPException:
    return HTTPException(status_code=_UPDATE_STATUS.get(exc.code, 400), detail=exc.code)


def _updates_out(db: Session, helper: ra.Helper) -> UpdatesOut:
    check = updates.stored_check(db)
    installed = server_version.installed()
    latest = check.get("latest") or None
    available = updates.is_newer(latest, installed)
    run = updates.run_state()
    helper_ok = helper.available()
    blocked: Optional[str] = None
    if available:
        if run["active"]:
            blocked = "running"
        elif not check.get("sums_url"):
            blocked = "no_checksums"
        elif not check.get("setup_url"):
            blocked = "no_setup"
        elif not helper_ok:
            blocked = "helper_unavailable"
    apks = android_app.find_apks()
    phone = apks.get("arm64") or apks.get("armv7")
    return UpdatesOut(
        installed_version=installed,
        phone_app_version=phone.version if phone else None,
        latest_version=latest,
        update_available=available,
        can_install=available and blocked is None,
        install_blocked=blocked,
        notes=check.get("notes"),
        checked_at=check.get("checked_at"),
        check_error=check.get("error"),
        helper_available=helper_ok,
        signer_configured=bool(settings.update_signer_subject.strip()),
        rollback_ready=updates.rollback_ready(),
        max_setup_mb=settings.update_max_setup_mb,
        run=UpdateRunOut(**run),
    )


@router.get("/updates", response_model=UpdatesOut)
def get_updates(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    helper: Annotated[ra.Helper, Depends(get_update_helper)],
) -> UpdatesOut:
    """Installed version, the bundled phone app, the latest published release
    (as of the last check), and the state of any update."""
    return _updates_out(db, helper)


@router.get("/updates/badge", response_model=UpdateBadgeOut)
def updates_badge(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> UpdateBadgeOut:
    """For the Admin link's badge in the nav: true when the last check found a
    release newer than the installed version. Cheap (no network, no task query),
    so every page can ask."""
    latest = updates.stored_check(db).get("latest") or None
    return UpdateBadgeOut(update_available=updates.is_newer(latest, server_version.installed()), latest_version=latest)


@router.post("/updates/check", response_model=UpdatesOut)
def check_updates(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    helper: Annotated[ra.Helper, Depends(get_update_helper)],
) -> UpdatesOut:
    """Ask GitHub now. Also runs daily from the scheduler. Network trouble is
    stored and shown, not raised. Nothing is installed."""
    updates.check_for_update(db)
    db.commit()
    return _updates_out(db, helper)


@router.get("/updates/run", response_model=UpdateRunOut)
def update_run(_admin: Annotated[User, Depends(require_admin)]) -> UpdateRunOut:
    """Live state of the running (or last) update. Poll while it is active; it
    keeps answering across the restart of the services."""
    return UpdateRunOut(**updates.run_state())


@router.post("/updates/apply", response_model=UpdateRunOut, status_code=202)
def apply_update(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    helper: Annotated[ra.Helper, Depends(get_update_helper)],
) -> UpdateRunOut:
    """Update to the latest published release. The server asks GitHub for the
    latest release again first (the stored answer may be a day old), downloads
    the Setup and SHA256SUMS.txt over https, checks the Setup against its line
    in the checksum list, then starts the SYSTEM updater task. A release
    without checksums is never installed."""
    try:
        state = updates.begin_apply(db, helper)
    except updates.UpdateError as exc:
        db.commit()  # keep the answer begin_apply just fetched from GitHub
        raise _update_http(exc) from exc
    _audit_event(db, admin.id, "update_started", request)
    db.commit()
    log.info("update to %s requested by %s (from GitHub)", state.get("to_version"), admin.username)
    return UpdateRunOut(**state)


@router.post("/updates/upload", response_model=UpdateRunOut, status_code=202)
async def upload_update(
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    helper: Annotated[ra.Helper, Depends(get_update_helper)],
) -> UpdateRunOut:
    """Update from a Setup you upload. The body is the raw exe; the admin's own
    password comes in the x-confirm-password header (percent-encoded) and is
    checked before one byte of the file is read or kept.

    The file is accepted only if its SHA-256 is the F7FIVE0-Setup-<version>.exe
    line of SHA256SUMS.txt on the published GitHub release for the version in
    its own version info, or it carries a valid Authenticode signature whose
    signer subject equals UPDATE_SIGNER_SUBJECT. Anything else is deleted and
    refused. The same or an older version is always refused."""
    try:
        updates.check_admin_password(
            admin.id, admin.password_hash, unquote(request.headers.get("x-confirm-password") or ""),
        )
    except updates.UpdateError as exc:
        if exc.code != "admin_password_required":
            _audit_event(db, admin.id, "update_password_failed", request)
            db.commit()
        raise _update_http(exc) from exc
    # The file is judged first: a file that isn't a published release or signed
    # is refused for that reason even on a server with no updater task. The
    # updater is only needed once the file is trusted (begin_run checks it).
    if updates.is_running():
        raise _update_http(updates.UpdateError("update_running"))
    max_bytes = updates.max_setup_bytes()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise _update_http(updates.UpdateError("too_large"))
    updates.clear_incoming()
    try:
        tmp, digest = await updates.stage_upload(request.stream(), updates.paths().incoming, max_bytes)
    except updates.UpdateError as exc:
        raise _update_http(exc) from exc
    try:
        trust = await run_in_threadpool(updates.verify_upload, tmp, digest, server_version.installed())
    except updates.UpdateError as exc:
        tmp.unlink(missing_ok=True)
        _audit_event(db, admin.id, "update_upload_refused", request)
        db.commit()
        log.info("update upload from %s refused: %s", admin.username, exc.code)
        raise _update_http(exc) from exc
    staged = updates.promote_upload(tmp, trust["version"])
    try:
        run_id = updates.begin_run(helper, trust["version"], trust["source"])
        state = updates.queue_run(helper, run_id, staged, digest, trust["version"], trust["source"])
    except updates.UpdateError as exc:
        staged.unlink(missing_ok=True)
        raise _update_http(exc) from exc
    _audit_event(db, admin.id, "update_started", request)
    db.commit()
    log.info("update to %s requested by %s (uploaded, %s)", trust["version"], admin.username, trust["source"])
    return UpdateRunOut(**state)


# ---------------------------------------------------------------------------
# Metadata: the TMDB key (Admin > Metadata)
# ---------------------------------------------------------------------------
def _metadata_out(db: Session) -> MetadataSettingsOut:
    src = tmdb_key.source(db)
    key = tmdb_key.saved(db) if src == "admin" else (settings.tmdb_api_key or "").strip()
    return MetadataSettingsOut(tmdb=TmdbKeyStatusOut(
        configured=src is not None, source=src, masked=tmdb_key.masked(key) if key else None,
    ))


@router.get("/metadata", response_model=MetadataSettingsOut)
def get_metadata_settings(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MetadataSettingsOut:
    return _metadata_out(db)


@router.post("/metadata/tmdb/test", response_model=TmdbKeyCheckOut)
def test_tmdb_key(
    body: TmdbKeyIn,
    _admin: Annotated[User, Depends(require_admin)],
) -> TmdbKeyCheckOut:
    """Ask TMDB whether a key works, without saving it."""
    result = tmdb_key.check(body.api_key)
    return TmdbKeyCheckOut(ok=result.ok, message=result.message)


@router.put("/metadata/tmdb", response_model=MetadataSettingsOut)
def put_tmdb_key(
    body: TmdbKeyIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MetadataSettingsOut:
    """Check the key with TMDB, save it, and refresh the library: movies and
    shows get matched and fetch posters on the next scan, and movies that
    were enriched while no key was set are enriched again."""
    result = tmdb_key.check(body.api_key)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message)
    tmdb_key.save(db, body.api_key)
    stale = db.scalars(select(Movie).where(
        Movie.tmdb_id.is_not(None),
        Movie.metadata_status.in_(("no_external_id", "failed")),
    )).all()
    for movie in stale:
        movie.metadata_synced_at = None
    db.commit()
    for movie in stale:
        scheduler.schedule_enrich_movie(movie.id)
    scheduler.trigger_full_sync_now()
    log.info("tmdb key saved from the admin page; re-enriching %d movie(s)", len(stale))
    return _metadata_out(db)


@router.delete("/metadata/tmdb", response_model=MetadataSettingsOut)
def delete_tmdb_key(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MetadataSettingsOut:
    """Remove the saved key. TMDB_API_KEY in .env (from Setup) applies again
    if it is set; otherwise TMDB is off."""
    tmdb_key.clear(db)
    db.commit()
    return _metadata_out(db)


# ---------------------------------------------------------------------------
# Reminders (banner in the web app)
# ---------------------------------------------------------------------------
@router.get("/reminders", response_model=list[ReminderOut])
def list_reminders(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ReminderOut]:
    return [
        ReminderOut(id=r.id, title=r.title, body=r.body, action_label=r.action_label, action_href=r.action_href)
        for r in reminders.active(db, admin.id)
    ]


@router.post("/reminders/{reminder_id}/snooze", status_code=204)
def snooze_reminder(
    reminder_id: str,
    body: ReminderSnoozeIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    try:
        reminders.snooze(db, admin.id, reminder_id, forever=body.forever)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_reminder")
    db.commit()
