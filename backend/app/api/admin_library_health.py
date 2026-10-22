"""Admin library health: missing-file cleanup and health counts.

Endpoints:
  GET  /api/admin/library/health
      Summary counts: missing files, eligible for cleanup, probe errors,
      unreachable folders, unmatched items, missing art.
  GET  /api/admin/library/health/missing-files
      Eligible missing-file candidates (7+ days, reachable folder).
  GET  /api/admin/library/health/files?state=missing|error&limit=&offset=
      Every missing file, or every file ffprobe could not read, newest problem
      first, a page at a time. The drill-down behind the count tiles.
  GET  /api/admin/library/health/unreachable-folders
      Library folders the service cannot open right now.
  DELETE /api/admin/library/health/missing-files/{media_file_id}
      Remove a single eligible candidate; deletes the item when its last
      file goes. Returns 409 if the file is back on disk.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.art import (
    ArtOverride, ENTITY_ALBUM, ENTITY_ARTIST, ENTITY_MOVIE, ENTITY_SERIES,
    ROLE_COVER, ROLE_POSTER, ROLE_THUMB,
)
from app.models.media_file import MediaFile, MediaKind, ScanState
from app.models.movie import Movie
from app.models.music import Album, Artist, MusicVideo, MusicVideoRelease, Track
from app.models.tv import Episode, Season, Series
from app.models.user import User
from app.services import library_folders, metadata_locks, nas_auth
from app.services.path_map import translate as translate_path


router = APIRouter(tags=["admin-library-health"])

_ELIGIBLE_DAYS = 7


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class HealthCounts(BaseModel):
    missing_files_total: int
    missing_files_eligible: int
    probe_errors: int
    unreachable_folders: int
    unmatched: dict[str, int]
    missing_art: dict[str, int]
    duplicate_movie_versions: int = 0
    duplicate_episode_versions: int = 0
    music_duplicates: int = 0
    flipflop_warnings: list[str] = []


class MissingFileItem(BaseModel):
    media_file_id: uuid.UUID
    path: str
    item_title: Optional[str]
    library_kind: Optional[str]
    days_missing: int


class HealthFileItem(BaseModel):
    media_file_id: uuid.UUID
    path: str
    item_title: Optional[str]
    library_kind: Optional[str]
    kind: str
    state: str
    # Days since the scan first missed it (missing files only).
    days_missing: Optional[int] = None
    # Whether this file can be removed now (missing 7+ days, folder reachable).
    eligible: bool = False


class HealthFilesPage(BaseModel):
    total: int
    items: list[HealthFileItem]


class UnreachableFolder(BaseModel):
    path: str
    library_kind: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_ELIGIBLE_DAYS)


def _all_folder_roots(db: Session) -> list[str]:
    """Flat list of all configured library folder paths (path-map translated)."""
    all_f = library_folders.all_folders(db)
    out: list[str] = []
    for paths in all_f.values():
        for p in paths:
            tp = translate_path(p, db) or p
            out.append(tp.rstrip("\\/"))
    return list(dict.fromkeys(out))  # deduplicate, preserve order


def _reachable_roots(db: Session) -> set[str]:
    """Folder roots that pass os.path.isdir after NAS connection."""
    try:
        nas_auth.ensure_all(db)
    except Exception:
        pass
    roots = _all_folder_roots(db)
    return {r for r in roots if os.path.isdir(r)}


def _folder_for_path(roots: list[str], path: str) -> Optional[str]:
    """The library root that contains `path`, or None."""
    p = (translate_path(path) or path).rstrip("\\/")
    for root in roots:
        r = root.rstrip("\\/")
        if p == r or p.startswith(r + os.sep) or p.startswith(r + "/") or p.startswith(r + "\\"):
            return root
    return None


def _item_title(db: Session, mf: MediaFile) -> Optional[str]:
    """Human-readable title for the item that owns this media file."""
    if mf.kind == MediaKind.movie:
        row = db.get(Movie, mf.ref_id)
        return row.title if row else None
    if mf.kind == MediaKind.episode:
        ep = db.get(Episode, mf.ref_id)
        if ep:
            ser = db.get(Series, ep.series_id)
            return f"{ser.title} S{ep.season_number:02d}E{ep.episode_number:02d}" if ser else ep.title
        return None
    if mf.kind == MediaKind.track:
        row = db.get(Track, mf.ref_id)
        return row.title if row else None
    if mf.kind == MediaKind.music_video:
        row = db.get(MusicVideo, mf.ref_id)
        return row.title if row else None
    return None


def _library_kind_for_file(db: Session, mf: MediaFile) -> Optional[str]:
    if mf.library_id is None:
        return None
    from app.models.library import Library
    lib = db.get(Library, mf.library_id)
    return lib.kind.value if lib else None


def _is_eligible(mf: MediaFile, reachable: set[str], all_roots: list[str]) -> bool:
    """True when the file meets the 7-day + reachable-folder criteria."""
    if mf.scan_state != ScanState.missing:
        return False
    if mf.missing_since is None:
        return False
    ms = mf.missing_since
    if ms.tzinfo is None:
        ms = ms.replace(tzinfo=timezone.utc)
    if ms > _cutoff():
        return False
    folder = _folder_for_path(all_roots, mf.path)
    return folder is not None and folder in reachable


def _days_missing(mf: MediaFile) -> int:
    ms = mf.missing_since
    if ms is None:
        return 0
    if ms.tzinfo is None:
        ms = ms.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ms).days


def _delete_item_if_last_file(db: Session, mf: MediaFile) -> None:
    """Delete the item row when this was its last media_file.

    Albums, seasons, series, and artists stay but become hidden from browse
    (the browse endpoints already filter for at least one ready file).
    Only deletes: Movie, Episode, Track, MusicVideo.
    Also removes metadata_locks for the deleted item.
    """
    kind = mf.kind
    ref_id = mf.ref_id

    has_more = db.scalar(
        select(func.count()).select_from(MediaFile).where(
            MediaFile.kind == kind,
            MediaFile.ref_id == ref_id,
            MediaFile.id != mf.id,
        )
    ) or 0
    if has_more > 0:
        return

    if kind == MediaKind.movie:
        row = db.get(Movie, ref_id)
        if row:
            db.delete(row)
        _clear_item_locks(db, "movie", ref_id)
    elif kind == MediaKind.episode:
        ep = db.get(Episode, ref_id)
        if ep:
            db.delete(ep)
        _clear_item_locks(db, "episode", ref_id)
    elif kind == MediaKind.track:
        from app.models.track_play import TrackPlay
        db.execute(update(TrackPlay).where(TrackPlay.track_id == ref_id).values(track_id=None))
        row = db.get(Track, ref_id)
        if row:
            db.delete(row)
        _clear_item_locks(db, "track", ref_id)
    elif kind == MediaKind.music_video:
        row = db.get(MusicVideo, ref_id)
        if row:
            db.delete(row)
        _clear_item_locks(db, "music_video", ref_id)


def _clear_item_locks(db: Session, kind: str, entity_id: uuid.UUID) -> None:
    from app.models.metadata_lock import MetadataLock
    db.execute(
        delete(MetadataLock).where(
            MetadataLock.entity_kind == kind,
            MetadataLock.entity_id == entity_id,
        )
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthCounts)
def get_health(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> HealthCounts:
    """Aggregate library health counts."""
    all_roots = _all_folder_roots(db)
    reachable = _reachable_roots(db)

    missing_total = db.scalar(
        select(func.count()).select_from(MediaFile).where(MediaFile.scan_state == ScanState.missing)
    ) or 0
    probe_errors = db.scalar(
        select(func.count()).select_from(MediaFile).where(MediaFile.scan_state == ScanState.error)
    ) or 0

    # Count eligible: missing_since old enough and folder reachable.
    cutoff = _cutoff()
    candidates = db.scalars(
        select(MediaFile).where(
            MediaFile.scan_state == ScanState.missing,
            MediaFile.missing_since.is_not(None),
            MediaFile.missing_since <= cutoff,
        )
    ).all()
    eligible = sum(1 for mf in candidates if _is_eligible(mf, reachable, all_roots))

    unreachable = len([r for r in all_roots if r not in reachable])

    # Unmatched counts (no external id).
    unmatched = {
        "movie": db.scalar(
            select(func.count()).select_from(Movie).where(
                Movie.tmdb_id.is_(None), Movie.radarr_id.is_(None),
            )
        ) or 0,
        "series": db.scalar(
            select(func.count()).select_from(Series).where(
                Series.tmdb_id.is_(None), Series.tvdb_id.is_(None), Series.sonarr_id.is_(None),
            )
        ) or 0,
        "artist": db.scalar(
            select(func.count()).select_from(Artist).where(
                Artist.mbid.is_(None), Artist.lidarr_id.is_(None),
            )
        ) or 0,
        "album": db.scalar(
            select(func.count()).select_from(Album).where(Album.mbid.is_(None))
        ) or 0,
    }

    # Missing art counts (no row for primary role).
    missing_art = {
        "movie": db.scalar(
            select(func.count()).select_from(Movie).where(
                ~exists(
                    select(ArtOverride.entity_id).where(
                        ArtOverride.entity_kind == ENTITY_MOVIE,
                        ArtOverride.entity_id == Movie.id,
                        ArtOverride.role == ROLE_POSTER,
                    )
                )
            )
        ) or 0,
        "series": db.scalar(
            select(func.count()).select_from(Series).where(
                ~exists(
                    select(ArtOverride.entity_id).where(
                        ArtOverride.entity_kind == ENTITY_SERIES,
                        ArtOverride.entity_id == Series.id,
                        ArtOverride.role == ROLE_POSTER,
                    )
                )
            )
        ) or 0,
        "artist": db.scalar(
            select(func.count()).select_from(Artist).where(
                ~exists(
                    select(ArtOverride.entity_id).where(
                        ArtOverride.entity_kind == ENTITY_ARTIST,
                        ArtOverride.entity_id == Artist.id,
                        ArtOverride.role == ROLE_THUMB,
                    )
                )
            )
        ) or 0,
        "album": db.scalar(
            select(func.count()).select_from(Album).where(
                ~exists(
                    select(ArtOverride.entity_id).where(
                        ArtOverride.entity_kind == ENTITY_ALBUM,
                        ArtOverride.entity_id == Album.id,
                        ArtOverride.role == ROLE_COVER,
                    )
                )
            )
        ) or 0,
    }

    # Duplicate versions: movies/episodes with 2+ ready media_files.
    from sqlalchemy import text as _text
    dup_movie_ids = db.scalars(
        select(MediaFile.ref_id).where(
            MediaFile.kind == MediaKind.movie,
            MediaFile.scan_state == ScanState.ready,
        ).group_by(MediaFile.ref_id).having(func.count(MediaFile.id) >= 2)
    ).all()
    duplicate_movie_versions = len(dup_movie_ids)

    dup_ep_ids = db.scalars(
        select(MediaFile.ref_id).where(
            MediaFile.kind == MediaKind.episode,
            MediaFile.scan_state == ScanState.ready,
        ).group_by(MediaFile.ref_id).having(func.count(MediaFile.id) >= 2)
    ).all()
    duplicate_episode_versions = len(dup_ep_ids)

    # Music duplicates: tracks with matching normalized tags and duration within 5s.
    music_dup_track_ids = _music_duplicate_track_ids(db)
    music_duplicates = len(music_dup_track_ids)

    from app.services.flipflop_guard import check_flipflop
    flipflop_warnings: list[str] = []
    for kind_val in ["movies", "tv", "music"]:
        flipflop_warnings.extend(check_flipflop(kind_val))

    return HealthCounts(
        missing_files_total=missing_total,
        missing_files_eligible=eligible,
        probe_errors=probe_errors,
        unreachable_folders=unreachable,
        unmatched=unmatched,
        missing_art=missing_art,
        duplicate_movie_versions=duplicate_movie_versions,
        duplicate_episode_versions=duplicate_episode_versions,
        music_duplicates=music_duplicates,
        flipflop_warnings=flipflop_warnings,
    )


@router.get("/health/missing-files", response_model=list[MissingFileItem])
def list_missing_files(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MissingFileItem]:
    """Eligible missing-file candidates (7+ days missing, reachable folder)."""
    all_roots = _all_folder_roots(db)
    reachable = _reachable_roots(db)
    cutoff = _cutoff()

    candidates = db.scalars(
        select(MediaFile).where(
            MediaFile.scan_state == ScanState.missing,
            MediaFile.missing_since.is_not(None),
            MediaFile.missing_since <= cutoff,
        ).order_by(MediaFile.missing_since)
    ).all()

    out: list[MissingFileItem] = []
    for mf in candidates:
        if not _is_eligible(mf, reachable, all_roots):
            continue
        out.append(MissingFileItem(
            media_file_id=mf.id,
            path=mf.path,
            item_title=_item_title(db, mf),
            library_kind=_library_kind_for_file(db, mf),
            days_missing=_days_missing(mf),
        ))
    return out


@router.get("/health/files", response_model=HealthFilesPage)
def list_health_files(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    state: Annotated[str, Query(pattern="^(missing|error)$")],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HealthFilesPage:
    """Every missing file (longest missing first) or every probe error (most
    recently seen first). The Missing files and Probe errors tiles open this."""
    wanted = ScanState.missing if state == "missing" else ScanState.error
    total = db.scalar(
        select(func.count()).select_from(MediaFile).where(MediaFile.scan_state == wanted)
    ) or 0
    q = select(MediaFile).where(MediaFile.scan_state == wanted)
    if wanted == ScanState.missing:
        q = q.order_by(MediaFile.missing_since.is_(None), MediaFile.missing_since, MediaFile.path)
    else:
        q = q.order_by(MediaFile.updated_at.desc(), MediaFile.path)
    rows = db.scalars(q.offset(offset).limit(limit)).all()

    all_roots: list[str] = []
    reachable: set[str] = set()
    if wanted == ScanState.missing and rows:
        all_roots = _all_folder_roots(db)
        reachable = _reachable_roots(db)

    items = [
        HealthFileItem(
            media_file_id=mf.id,
            path=mf.path,
            item_title=_item_title(db, mf),
            library_kind=_library_kind_for_file(db, mf),
            kind=mf.kind.value,
            state=state,
            days_missing=_days_missing(mf) if wanted == ScanState.missing else None,
            eligible=wanted == ScanState.missing and _is_eligible(mf, reachable, all_roots),
        )
        for mf in rows
    ]
    return HealthFilesPage(total=total, items=items)


@router.get("/health/unreachable-folders", response_model=list[UnreachableFolder])
def list_unreachable_folders(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[UnreachableFolder]:
    """Library folders the service cannot open right now (path-map translated),
    the same test the Unreachable folders count uses."""
    reachable = _reachable_roots(db)
    out: list[UnreachableFolder] = []
    seen: set[str] = set()
    for kind, paths in library_folders.all_folders(db).items():
        for p in paths:
            tp = (translate_path(p, db) or p).rstrip("\\/")
            if tp in reachable or tp in seen:
                continue
            seen.add(tp)
            out.append(UnreachableFolder(path=tp, library_kind=kind))
    return out


@router.delete("/health/missing-files/{media_file_id}", status_code=204)
def delete_missing_file(
    media_file_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Remove an eligible missing file and its item if it was the last file.

    Re-checks 7-day + reachable-folder eligibility before deleting.
    Returns 409 ``file_present`` if the file exists on disk again.
    Returns 409 ``not_eligible`` if the file no longer meets the criteria.
    """
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="media_file_not_found")

    all_roots = _all_folder_roots(db)
    try:
        nas_auth.ensure_all(db)
    except Exception:
        pass
    reachable = _reachable_roots(db)

    # Re-check eligibility.
    if not _is_eligible(mf, reachable, all_roots):
        raise HTTPException(status_code=409, detail="not_eligible")

    # Re-check that the file isn't actually there.
    translated_path = translate_path(mf.path, db) or mf.path
    if os.path.exists(translated_path):
        raise HTTPException(status_code=409, detail="file_present")

    # Delete the item if this was its last file, then delete the media file.
    _delete_item_if_last_file(db, mf)
    from app.models.playback import WatchHistory
    db.execute(update(WatchHistory).where(WatchHistory.media_file_id == mf.id).values(media_file_id=None))
    db.delete(mf)
    db.commit()


# ---------------------------------------------------------------------------
# Music duplicate detection helpers
# ---------------------------------------------------------------------------
def _music_duplicate_track_ids(db: Session) -> set[uuid.UUID]:
    """Return the set of track ids involved in any same-tags duplicate group."""
    from app.services.art_sources.names import match_key

    rows = db.execute(
        select(
            Track.id,
            Track.title,
            Track.duration_sec,
            Artist.name.label("artist_name"),
            Album.title.label("album_title"),
        )
        .join(Album, Track.album_id == Album.id)
        .join(Artist, Album.artist_id == Artist.id)
        .where(
            exists(
                select(MediaFile.id).where(
                    MediaFile.kind == MediaKind.track,
                    MediaFile.ref_id == Track.id,
                    MediaFile.scan_state == ScanState.ready,
                )
            )
        )
    ).all()

    # Build normalized key -> list of (track_id, duration_sec)
    from collections import defaultdict
    by_key: dict[str, list] = defaultdict(list)
    for row in rows:
        key = (
            match_key(row.title or "")
            + "|" + match_key(row.artist_name or "")
            + "|" + match_key(row.album_title or "")
        )
        by_key[key].append((row.id, row.duration_sec))

    dup_ids: set[uuid.UUID] = set()
    for key, entries in by_key.items():
        if len(entries) < 2:
            continue
        # Find pairs within 5 s of each other
        for i, (tid_a, dur_a) in enumerate(entries):
            for tid_b, dur_b in entries[i + 1:]:
                if dur_a is None or dur_b is None:
                    if dur_a is None and dur_b is None:
                        dup_ids.add(tid_a)
                        dup_ids.add(tid_b)
                elif abs(dur_a - dur_b) <= 5:
                    dup_ids.add(tid_a)
                    dup_ids.add(tid_b)
    return dup_ids


# ---------------------------------------------------------------------------
# New endpoints
# ---------------------------------------------------------------------------
class MusicDuplicateTrack(BaseModel):
    track_id: uuid.UUID
    title: Optional[str]
    artist: Optional[str]
    album: Optional[str]
    duration_sec: Optional[int]
    path: Optional[str]
    media_file_id: Optional[uuid.UUID]


class MusicDuplicateGroup(BaseModel):
    reason: str
    tracks: list[MusicDuplicateTrack]


@router.get("/health/music-duplicates", response_model=list[MusicDuplicateGroup])
def list_music_duplicates(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MusicDuplicateGroup]:
    """Groups of tracks with matching normalized title+artist+album and duration within 5 s."""
    from app.services.art_sources.names import match_key
    from collections import defaultdict

    rows = db.execute(
        select(
            Track.id,
            Track.title,
            Track.duration_sec,
            Artist.name.label("artist_name"),
            Album.title.label("album_title"),
        )
        .join(Album, Track.album_id == Album.id)
        .join(Artist, Album.artist_id == Artist.id)
        .where(
            exists(
                select(MediaFile.id).where(
                    MediaFile.kind == MediaKind.track,
                    MediaFile.ref_id == Track.id,
                    MediaFile.scan_state == ScanState.ready,
                )
            )
        )
    ).all()

    # Build normalized key -> list of track info
    by_key: dict[str, list] = defaultdict(list)
    for row in rows:
        key = (
            match_key(row.title or "")
            + "|" + match_key(row.artist_name or "")
            + "|" + match_key(row.album_title or "")
        )
        by_key[key].append(row)

    groups: list[MusicDuplicateGroup] = []
    seen_groups: set[frozenset] = set()
    for key, entries in by_key.items():
        if len(entries) < 2:
            continue
        # Find clusters of tracks within 5 s of each other
        clustered: list[list] = []
        for entry in entries:
            placed = False
            for cluster in clustered:
                rep = cluster[0]
                dur_a = entry.duration_sec
                dur_b = rep.duration_sec
                if dur_a is None and dur_b is None:
                    cluster.append(entry)
                    placed = True
                    break
                if dur_a is not None and dur_b is not None and abs(dur_a - dur_b) <= 5:
                    cluster.append(entry)
                    placed = True
                    break
            if not placed:
                clustered.append([entry])

        for cluster in clustered:
            if len(cluster) < 2:
                continue
            gkey = frozenset(r.id for r in cluster)
            if gkey in seen_groups:
                continue
            seen_groups.add(gkey)
            track_rows = []
            for r in cluster:
                mf = db.scalar(
                    select(MediaFile).where(
                        MediaFile.kind == MediaKind.track,
                        MediaFile.ref_id == r.id,
                        MediaFile.scan_state == ScanState.ready,
                    ).limit(1)
                )
                track_rows.append(MusicDuplicateTrack(
                    track_id=r.id,
                    title=r.title,
                    artist=r.artist_name,
                    album=r.album_title,
                    duration_sec=r.duration_sec,
                    path=mf.path if mf else None,
                    media_file_id=mf.id if mf else None,
                ))
            groups.append(MusicDuplicateGroup(reason="same_tags", tracks=track_rows))
    return groups


@router.post("/movies/{movie_id}/versions/{media_file_id}/prefer", status_code=204)
def prefer_movie_version(
    movie_id: uuid.UUID,
    media_file_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Set is_preferred_version = True on the given file, null on all siblings."""
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="movie_not_found")
    mf = db.get(MediaFile, media_file_id)
    if mf is None or mf.kind != MediaKind.movie or mf.ref_id != movie_id:
        raise HTTPException(status_code=404, detail="media_file_not_found")
    # Clear siblings
    db.execute(
        update(MediaFile)
        .where(MediaFile.kind == MediaKind.movie, MediaFile.ref_id == movie_id)
        .values(is_preferred_version=None)
    )
    mf.is_preferred_version = True
    db.commit()


@router.post("/episodes/{episode_id}/versions/{media_file_id}/prefer", status_code=204)
def prefer_episode_version(
    episode_id: uuid.UUID,
    media_file_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Set is_preferred_version = True on the given file, null on all siblings."""
    from app.models.tv import Episode
    ep = db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="episode_not_found")
    mf = db.get(MediaFile, media_file_id)
    if mf is None or mf.kind != MediaKind.episode or mf.ref_id != episode_id:
        raise HTTPException(status_code=404, detail="media_file_not_found")
    db.execute(
        update(MediaFile)
        .where(MediaFile.kind == MediaKind.episode, MediaFile.ref_id == episode_id)
        .values(is_preferred_version=None)
    )
    mf.is_preferred_version = True
    db.commit()
