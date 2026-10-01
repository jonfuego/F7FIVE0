"""Media request flow: search upstream, request, admin approve/deny.

Users search Radarr/Sonarr's lookup, file a request, and watch its status.
Admins approve (which adds the item to Radarr or Sonarr) or deny. The sync
job flips approved requests to `available` when the item lands in the
library (see services/sync.py _resolve_requests). No download is ever
exposed to a user; this only files acquisition with the *arr stack.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, require_admin
from app.api.schemas import (
    RequestCreate, RequestDeny, RequestOut, RequestSearchResultOut,
)
from app.config import settings
from app.models.movie import Movie
from app.models.request import (
    KIND_MOVIE, KIND_SERIES, Request, STATUS_APPROVED, STATUS_AVAILABLE,
    STATUS_DENIED, STATUS_PENDING,
)
from app.models.tv import Series
from app.models.user import User
from app.services.arr._base import ArrClientError
from app.services.arr.radarr import RadarrClient
from app.services.arr.sonarr import SonarrClient


router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def requests_enabled(kind: str) -> bool:
    """Requests need the matching *arr: Radarr for movies, Sonarr for series."""
    if kind == KIND_MOVIE:
        return bool(settings.radarr_api_key)
    if kind == KIND_SERIES:
        return bool(settings.sonarr_api_key)
    return False


def _require_enabled(kind: str) -> None:
    if not requests_enabled(kind):
        raise HTTPException(status_code=409, detail="requests_disabled")


def _poster_from_images(images: Optional[list], cover_type: str = "poster") -> Optional[str]:
    for img in images or []:
        if (img or {}).get("coverType") == cover_type:
            url = img.get("remoteUrl") or img.get("url")
            if url:
                return url
    for img in images or []:
        url = (img or {}).get("remoteUrl") or (img or {}).get("url")
        if url:
            return url
    return None


def _open_request_ids(db: Session, kind: str) -> set[str]:
    """external_ids of this kind that already have a non-denied request."""
    rows = db.scalars(
        select(Request.external_id).where(
            Request.kind == kind,
            Request.status != STATUS_DENIED,
        )
    ).all()
    return set(rows)


def _to_out(req: Request, *, requested_by: Optional[str] = None) -> RequestOut:
    out = RequestOut.model_validate(req)
    out.requested_by = requested_by
    return out


# ---------------------------------------------------------------------------
# Search (any user)
# ---------------------------------------------------------------------------
@router.get("/search", response_model=list[RequestSearchResultOut])
def search_upstream(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=200),
    kind: str = Query(..., pattern="^(movie|series)$"),
) -> list[RequestSearchResultOut]:
    """Proxy the matching *arr lookup and annotate each hit with whether it
    is already in the library or already has an open request."""
    _require_enabled(kind)
    try:
        if kind == KIND_MOVIE:
            with RadarrClient(settings.radarr_url, settings.radarr_api_key) as rc:
                raw = rc.movie_lookup(q)
        else:
            with SonarrClient(settings.sonarr_url, settings.sonarr_api_key) as sc:
                raw = sc.series_lookup(q)
    except ArrClientError as exc:
        raise HTTPException(status_code=502, detail=f"arr_lookup_failed: {exc}")

    open_ids = _open_request_ids(db, kind)

    results: list[RequestSearchResultOut] = []
    for p in raw or []:
        if kind == KIND_MOVIE:
            ext = p.get("tmdbId")
            if not ext:
                continue
            ext = str(ext)
            in_lib = db.scalar(
                select(Movie.id).where(Movie.tmdb_id == int(ext)).limit(1)
            ) is not None
        else:
            ext = p.get("tvdbId")
            if not ext:
                continue
            ext = str(ext)
            in_lib = db.scalar(
                select(Series.id).where(Series.tvdb_id == int(ext)).limit(1)
            ) is not None
        results.append(
            RequestSearchResultOut(
                kind=kind,
                external_id=ext,
                title=p.get("title") or "Untitled",
                year=p.get("year"),
                poster_url=_poster_from_images(p.get("images")),
                overview=p.get("overview"),
                in_library=in_lib,
                requested=ext in open_ids,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Create + my requests (any user)
# ---------------------------------------------------------------------------
@router.post("", response_model=RequestOut, status_code=201)
def create_request(
    body: RequestCreate,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RequestOut:
    """File a request. Deduped against any existing non-denied request for
    the same (kind, external_id) by the partial unique index; a duplicate
    returns 409."""
    _require_enabled(body.kind)
    existing = db.scalar(
        select(Request).where(
            Request.kind == body.kind,
            Request.external_id == body.external_id,
            Request.status != STATUS_DENIED,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="already_requested")

    req = Request(
        user_id=user.id,
        kind=body.kind,
        title=body.title,
        year=body.year,
        external_id=body.external_id,
        poster_url=body.poster_url,
        status=STATUS_PENDING,
    )
    db.add(req)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against the partial unique index. Treat as a dup.
        db.rollback()
        raise HTTPException(status_code=409, detail="already_requested")
    db.refresh(req)
    return _to_out(req)


@router.get("/mine", response_model=list[RequestOut])
def my_requests(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RequestOut]:
    rows = db.scalars(
        select(Request)
        .where(Request.user_id == user.id)
        .order_by(Request.created_at.desc())
    ).all()
    return [_to_out(r) for r in rows]


# ---------------------------------------------------------------------------
# Admin: list + approve + deny
# ---------------------------------------------------------------------------
@router.get("", response_model=list[RequestOut])
def list_requests(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    status: Optional[str] = Query(
        default=None, pattern="^(pending|approved|denied|available)$",
    ),
) -> list[RequestOut]:
    """All requests, newest first, optionally filtered by status. Each row
    carries the requester's display name for the admin queue."""
    stmt = (
        select(Request, User.display_name)
        .join(User, User.id == Request.user_id)
        .order_by(Request.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Request.status == status)
    rows = db.execute(stmt).all()
    return [_to_out(r, requested_by=name) for r, name in rows]


@router.post("/{request_id}/approve", response_model=RequestOut)
def approve_request(
    request_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RequestOut:
    """Approve a pending request and add it to Radarr/Sonarr.

    Quality profile id and root folder come from settings, not hardcoded;
    an unset pair is a 422 so a misconfigured deploy fails loudly instead of
    silently dropping the request. Status flips to approved; the sync job
    later flips it to available when the file lands."""
    req = db.get(Request, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="request_not_found")
    if req.status != STATUS_PENDING:
        raise HTTPException(status_code=409, detail=f"request_not_pending: {req.status}")

    try:
        if req.kind == KIND_MOVIE:
            if not settings.radarr_quality_profile_id or not settings.radarr_root_folder:
                raise HTTPException(
                    status_code=422,
                    detail="radarr_quality_profile_id / radarr_root_folder not configured",
                )
            with RadarrClient(settings.radarr_url, settings.radarr_api_key) as rc:
                rc.add_movie(
                    int(req.external_id),
                    settings.radarr_quality_profile_id,
                    settings.radarr_root_folder,
                )
        else:
            if not settings.sonarr_quality_profile_id or not settings.sonarr_root_folder:
                raise HTTPException(
                    status_code=422,
                    detail="sonarr_quality_profile_id / sonarr_root_folder not configured",
                )
            with SonarrClient(settings.sonarr_url, settings.sonarr_api_key) as sc:
                sc.add_series(
                    int(req.external_id),
                    settings.sonarr_quality_profile_id,
                    settings.sonarr_root_folder,
                )
    except ArrClientError as exc:
        raise HTTPException(status_code=502, detail=f"arr_add_failed: {exc}")

    req.status = STATUS_APPROVED
    db.commit()
    db.refresh(req)
    return _to_out(req)


@router.post("/{request_id}/deny", response_model=RequestOut)
def deny_request(
    request_id: uuid.UUID,
    body: RequestDeny,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> RequestOut:
    """Deny a request with an optional note. Denied rows free the
    (kind, external_id) slot so the title can be requested again later."""
    req = db.get(Request, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="request_not_found")
    req.status = STATUS_DENIED
    req.note = body.note
    req.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)
    return _to_out(req)
