"""Admin library health: missing-file cleanup and health counts.

Endpoints:
  GET  /api/admin/library/health
      Summary counts: missing files, eligible for cleanup, probe errors,
      unreachable folders, unmatched items, missing art.
  GET  /api/admin/library/health/missing-files
      Eligible missing-file candidates (7+ days, reachable folder).
  DELETE /api/admin/library/health/missing-files/{media_file_id}
      Remove a single eligible candidate; deletes the item when its last
      file goes. Returns 409 if the file is back on disk.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
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


class MissingFileItem(BaseModel):
    media_file_id: uuid.UUID
    path: str
    item_title: Optional[str]
    library_kind: Optional[str]
    days_missing: int


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

    return HealthCounts(
        missing_files_total=missing_total,
        missing_files_eligible=eligible,
        probe_errors=probe_errors,
        unreachable_folders=unreachable,
        unmatched=unmatched,
        missing_art=missing_art,
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
