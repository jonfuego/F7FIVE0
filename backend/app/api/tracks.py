"""Per-track smart-audio read endpoints (Phase 2).

Mounted at `/api` in main.py alongside the library + auto-playlist routers.

    GET /api/tracks/{track_id}/loudness  -> { integrated_lufs, track_gain_db, album_gain_db }
    GET /api/tracks/{track_id}/waveform  -> { peaks: number[], version: number }
    GET /api/tracks/{track_id}/lyrics    -> { synced, lines, text, source }
    GET /api/tracks/{track_id}/similar   -> { items: [QueueItem, ...] }

Loudness and waveform read the precomputed `track_audio_analysis` row and
return nulls / an empty list when the track has not been analyzed yet. Lyrics
resolve at request time from the `.lrc` sidecar or embedded tags (cheap, no
ffmpeg pass needed for the sidecar). Similar delegates to the auto-playlist
similarity service, which falls back to same-artist / same-genre.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models.audio_analysis import TrackAudioAnalysis
from app.models.media_file import MediaFile, MediaKind
from app.models.music import Track
from app.models.user import User
from app.services import auto_playlist as auto_playlist_svc
from app.services import lyrics as lyrics_svc
from app.services import path_map


router = APIRouter()

DEFAULT_SIMILAR_LIMIT = 50
MAX_SIMILAR_LIMIT = 200


def _require_track(db: Session, track_id: uuid.UUID) -> Track:
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="track_not_found")
    return track


def _track_media_file(db: Session, track_id: uuid.UUID) -> Optional[MediaFile]:
    """The lowest-id media file for a track, if any (lyrics need the path)."""
    return db.execute(
        select(MediaFile)
        .where(MediaFile.kind == MediaKind.track, MediaFile.ref_id == track_id)
        .order_by(MediaFile.id)
        .limit(1)
    ).scalars().first()


@router.get("/tracks/{track_id}/loudness")
def get_loudness(
    track_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    _require_track(db, track_id)
    row = db.execute(
        select(TrackAudioAnalysis).where(TrackAudioAnalysis.track_id == track_id)
    ).scalars().first()
    if row is None:
        return {"integrated_lufs": None, "track_gain_db": None, "album_gain_db": None}
    return {
        "integrated_lufs": row.integrated_lufs,
        "track_gain_db": row.track_gain_db,
        "album_gain_db": row.album_gain_db,
    }


@router.get("/tracks/{track_id}/waveform")
def get_waveform(
    track_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    _require_track(db, track_id)
    row = db.execute(
        select(TrackAudioAnalysis).where(TrackAudioAnalysis.track_id == track_id)
    ).scalars().first()
    if row is None or not row.waveform_peaks:
        return {"peaks": [], "version": 0}
    return {
        "peaks": list(row.waveform_peaks),
        "version": int(row.analysis_version or 0),
    }


@router.get("/tracks/{track_id}/lyrics")
def get_lyrics(
    track_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    _require_track(db, track_id)
    mf = _track_media_file(db, track_id)
    if mf is None:
        return {"synced": False, "lines": None, "text": None, "source": None}
    # Paths are stored canonically; translate defensively in case a legacy row
    # still carries a mapped drive letter.
    resolved = path_map.translate(mf.path) or mf.path
    result = lyrics_svc.resolve_lyrics(resolved)
    return {
        "synced": result.synced,
        "lines": result.lines,
        "text": result.text,
        "source": result.source,
    }


@router.get("/tracks/{track_id}/similar")
def get_similar(
    track_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_SIMILAR_LIMIT, ge=1, le=MAX_SIMILAR_LIMIT),
) -> dict[str, Any]:
    _require_track(db, track_id)
    items, _candidates, _fallback = auto_playlist_svc.similar_tracks(
        db, track_id, limit,
    )
    return {"items": items}
