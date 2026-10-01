"""Auto-playlist read endpoints.

All eleven generated-playlist kinds live under one router. Each handler
delegates to a helper in `app.services.auto_playlist` for the SQL,
applies the limit cap, and packages the response in the shape the design
spec calls for:

    { "kind": "<slug>", "params": { ... }, "items": [...], "diagnostic": {...} }

The router is mounted at `/api` in `main.py` (matching the library
router convention). Browser-side calls go through the BFF at
`/api/library/auto-playlist/...`, which strips `library/` and forwards
to `/api/auto-playlist/...` here.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db
from app.models.user import User
from app.services import auto_playlist as svc

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


router = APIRouter()


def _clamp_limit(limit: int) -> int:
    """Clamp the requested limit to the spec's hard cap. The Query()
    declaration already bounds the input (ge=1, le=MAX_LIMIT), so this
    is only here to give callers a single consistent helper if a kind
    ever needs a different cap."""
    return max(1, min(MAX_LIMIT, limit))


def _shape(
    kind: str,
    params: dict[str, Any],
    items: list[dict[str, Any]],
    candidates: int,
    fallback: Optional[str] = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "candidates_considered": int(candidates),
        "filtered_out": max(0, int(candidates) - len(items)),
    }
    if fallback is not None:
        diagnostic["fallback"] = fallback
    return {
        "kind": kind,
        "params": params,
        "items": items,
        "diagnostic": diagnostic,
    }


# ---------------------------------------------------------------------------
# Phase 5a
# ---------------------------------------------------------------------------
@router.get("/auto-playlist/random")
def get_random(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates = svc.random_pick(db, n)
    return _shape("random", {"limit": n}, items, candidates)


@router.get("/auto-playlist/by-artist/{artist_id}")
def get_by_artist(
    artist_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates = svc.by_artist(db, artist_id, n)
    return _shape("by-artist", {"artist_id": str(artist_id), "limit": n}, items, candidates)


@router.get("/auto-playlist/recently-added")
def get_recently_added(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates = svc.recently_added(db, n)
    return _shape("recently-added", {"limit": n}, items, candidates)


@router.get("/auto-playlist/by-year/{year}")
def get_by_year(
    year: int,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    if year < 1900 or year > 2100:
        raise HTTPException(status_code=422, detail="year_out_of_range")
    n = _clamp_limit(limit)
    items, candidates = svc.by_year(db, year, n)
    return _shape("by-year", {"year": year, "limit": n}, items, candidates)


@router.get("/auto-playlist/by-decade/{decade}")
def get_by_decade(
    decade: int,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    # Decades are 4-digit start years aligned to ten (1970, 1980, ...).
    # Normalize a stray year input down to its decade so the picker is
    # forgiving, and 422 on anything way out of range.
    if decade < 1900 or decade > 2100:
        raise HTTPException(status_code=422, detail="decade_out_of_range")
    decade = (decade // 10) * 10
    n = _clamp_limit(limit)
    items, candidates = svc.by_decade(db, decade, n)
    return _shape("by-decade", {"decade": decade, "limit": n}, items, candidates)


@router.get("/auto-playlist/continue-listening")
def get_continue_listening(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates = svc.continue_listening(db, user.id, n)
    return _shape("continue-listening", {"limit": n}, items, candidates)


# ---------------------------------------------------------------------------
# Phase 5b
# ---------------------------------------------------------------------------
@router.get("/auto-playlist/by-genre/{genre_slug}")
def get_by_genre(
    genre_slug: str,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    slug = (genre_slug or "").strip()
    if not slug:
        raise HTTPException(status_code=422, detail="genre_slug_required")
    n = _clamp_limit(limit)
    items, candidates = svc.by_genre(db, slug, n)
    return _shape("by-genre", {"genre_slug": slug, "limit": n}, items, candidates)


# ---------------------------------------------------------------------------
# Phase 5c
# ---------------------------------------------------------------------------
@router.get("/auto-playlist/most-played")
def get_most_played(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    window: str = Query("all", pattern="^(all|30d|90d)$"),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates, fallback = svc.most_played(db, user.id, n, window)
    return _shape(
        "most-played", {"limit": n, "window": window}, items, candidates, fallback,
    )


@router.get("/auto-playlist/never-played")
def get_never_played(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates, fallback = svc.never_played(db, user.id, n)
    return _shape("never-played", {"limit": n}, items, candidates, fallback)


@router.get("/auto-playlist/recently-played")
def get_recently_played(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates = svc.recently_played(db, user.id, n)
    return _shape("recently-played", {"limit": n}, items, candidates)


@router.get("/auto-playlist/track-radio/{track_id}")
def get_track_radio(
    track_id: uuid.UUID,
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates, fallback = svc.track_radio(db, track_id, n)
    return _shape(
        "track-radio", {"track_id": str(track_id), "limit": n},
        items, candidates, fallback,
    )


@router.get("/auto-playlist/artist-radio/{artist_id}")
def get_artist_radio(
    artist_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(DEFAULT_LIMIT, ge=1),
) -> dict[str, Any]:
    n = _clamp_limit(limit)
    items, candidates, fallback = svc.artist_radio(db, user.id, artist_id, n)
    return _shape(
        "artist-radio", {"artist_id": str(artist_id), "limit": n},
        items, candidates, fallback,
    )
