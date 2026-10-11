"""Art endpoints.

Two surfaces:

- /api/admin/art/<kind>/<id>/<role>  (POST upload / POST from-url / DELETE)
  Admin-only writes. Creates or replaces an override row, stores the
  image under settings.art_root, emits an auth_audit event.

- /api/art/<kind>/<id>/<role>  (GET)
  Authenticated read. Streams the stored file back so the browser can
  load overridden art as an <img src>. Falls through to 404 if the
  requested (kind, id, role) has no override.

Write paths mutate two places: the DB row via `services/art.py` helpers
and an `auth_events` row for the audit trail. Both live in the same
SQLAlchemy session so either both commit or neither does.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import (
    APIRouter, Depends, File, Header, HTTPException, Request, UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_bearer_token, get_db, require_admin
from app.models.art import ArtOverride
from app.models.user import AuthEvent, User
from app.services import art as art_service
from app.services import art_search as art_search_service
from app.services import security as security_service
from app.services.arr._base import ArrClientError
from app.services.signed_urls import session_authorizes


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ArtFromUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class ArtFromSearchRequest(BaseModel):
    source: str = Field(min_length=1, max_length=32)
    ref: str = Field(min_length=1, max_length=2048)


class ArtCandidateOut(BaseModel):
    source: str
    ref: str
    url: str
    label: str


class ArtSearchOut(BaseModel):
    """Search tab response: candidate tiles plus friendly notes.

    `notes` are short lines for the modal's callouts (a source that did not
    answer, or one that is not set up). Never raw error codes.
    """

    candidates: list[ArtCandidateOut]
    notes: list[str] = []


class ArtOverrideOut(BaseModel):
    entity_kind: str
    entity_id: uuid.UUID
    role: str
    source_kind: str
    source_ref: Optional[str] = None
    set_at: datetime


def _serialize(row: ArtOverride) -> ArtOverrideOut:
    return ArtOverrideOut(
        entity_kind=row.entity_kind,
        entity_id=row.entity_id,
        role=row.role,
        source_kind=row.source_kind,
        source_ref=row.source_ref,
        set_at=row.set_at,
    )


def _audit(
    db: Session, user_id: uuid.UUID, event: str, request: Request,
) -> None:
    ip = getattr(request.state, "client_ip", None)
    ua = request.headers.get("user-agent")
    db.add(
        AuthEvent(
            user_id=user_id,
            event=event,
            ip=ip if ip and ip != "unknown" else None,
            user_agent=ua[:512] if ua else None,
            at=datetime.now(timezone.utc),
        )
    )


# ---------------------------------------------------------------------------
# Admin write router: mounted under /api/admin/art
# ---------------------------------------------------------------------------
admin_router = APIRouter()


@admin_router.post(
    "/{entity_kind}/{entity_id}/{role}",
    response_model=ArtOverrideOut,
    status_code=201,
)
async def upload_art(
    entity_kind: str,
    entity_id: str,
    role: str,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> ArtOverrideOut:
    """Upload an image and pin it as the override for this entity+role."""
    data = await file.read()
    try:
        entity_id = art_service.parse_entity_id(entity_kind, entity_id)
        row = art_service.save_upload_bytes(
            db,
            entity_kind=entity_kind,
            entity_id=entity_id,
            role=role,
            data=data,
            set_by_user_id=admin.id,
            source_kind="upload",
            source_ref=file.filename,
        )
    except art_service.ArtValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    _audit(db, admin.id, "art_override_set", request)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@admin_router.post(
    "/{entity_kind}/{entity_id}/{role}/from-url",
    response_model=ArtOverrideOut,
    status_code=201,
)
def set_art_from_url(
    entity_kind: str,
    entity_id: str,
    role: str,
    body: ArtFromUrlRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArtOverrideOut:
    """Fetch an image from an arbitrary URL and pin it."""
    try:
        entity_id = art_service.parse_entity_id(entity_kind, entity_id)
        row = art_service.fetch_and_save_url(
            db,
            entity_kind=entity_kind,
            entity_id=entity_id,
            role=role,
            url=body.url,
            set_by_user_id=admin.id,
            source_kind="url",
        )
    except art_service.ArtValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    _audit(db, admin.id, "art_override_set", request)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@admin_router.delete(
    "/{entity_kind}/{entity_id}/{role}", status_code=204,
)
def clear_art(
    entity_kind: str,
    entity_id: str,
    role: str,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Drop the override. Native column value re-emerges on next read."""
    try:
        art_service.validate_kind_role(entity_kind, role)
        entity_id = art_service.parse_entity_id(entity_kind, entity_id)
    except art_service.ArtValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    removed = art_service.clear_override(
        db,
        entity_kind=entity_kind,
        entity_id=entity_id,
        role=role,
    )
    if not removed:
        # 404 so the UI can show "already cleared" rather than pretending
        # it did something.
        raise HTTPException(status_code=404, detail="override_not_found")
    _audit(db, admin.id, "art_override_cleared", request)
    db.commit()


@admin_router.get("/search", response_model=ArtSearchOut)
def search_art(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    kind: str,
    id: uuid.UUID,
) -> ArtSearchOut:
    """Aggregate candidate art from every configured source for (kind, id).

    Validates kind against the same map the write paths use so callers
    can't probe arbitrary kinds. Each source is best-effort: an
    unconfigured or unreachable source becomes a friendly note rather than
    a 5xx, so the modal renders candidates from the sources that did answer
    plus callouts for the ones that didn't.
    """
    if kind not in art_service._VALID_ROLES:
        raise HTTPException(
            status_code=404, detail=f"unsupported entity kind: {kind}",
        )
    try:
        candidates, notes = art_search_service.search_candidates_with_notes(
            db, kind=kind, entity_id=id,
        )
    except ArrClientError as exc:
        # Defensive: the aggregator catches per-source failures itself, so
        # this only fires on an unexpected hard error. Degrade gracefully
        # so the admin can still fall back to Upload or Paste URL.
        import logging
        logging.getLogger("f7five0.art").warning(
            "art search aggregator failed for %s/%s: %s", kind, id, exc,
        )
        return ArtSearchOut(candidates=[], notes=["Search did not answer."])
    return ArtSearchOut(
        candidates=[ArtCandidateOut(**c) for c in candidates],
        notes=notes,
    )


@admin_router.post(
    "/{entity_kind}/{entity_id}/{role}/from-search",
    response_model=ArtOverrideOut,
    status_code=201,
)
def set_art_from_search(
    entity_kind: str,
    entity_id: str,
    role: str,
    body: ArtFromSearchRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> ArtOverrideOut:
    """Apply a candidate from a prior /search call.

    The body carries `{source, ref}`. We re-run the aggregator and match
    on those fields rather than trusting an arbitrary URL the modal
    posted back; this keeps the trust boundary at the *arr providers we
    queried in the first place. The matched candidate's URL is then
    fetched + validated via the same path /from-url uses, so the 10 MB
    cap and Pillow decode apply uniformly.
    """
    try:
        art_service.validate_kind_role(entity_kind, role)
        entity_id = art_service.parse_entity_id(entity_kind, entity_id)
    except art_service.ArtValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    try:
        candidates = art_search_service.search_candidates(
            db, kind=entity_kind, entity_id=entity_id,
        )
    except ArrClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"search_provider_unavailable: {exc}",
        )

    match = next(
        (
            c for c in candidates
            if c.get("source") == body.source and c.get("ref") == body.ref
        ),
        None,
    )
    if match is None:
        raise HTTPException(status_code=400, detail="unknown_search_ref")

    try:
        row = art_service.fetch_and_save_url(
            db,
            entity_kind=entity_kind,
            entity_id=entity_id,
            role=role,
            url=match["url"],
            set_by_user_id=admin.id,
            source_kind=body.source,
        )
        # fetch_and_save_url stamps source_ref to the URL it downloaded.
        # Replace it with the caller's ref so the override row records
        # the provider identifier, matching the ADR's source_ref intent.
        row.source_ref = body.ref
        db.flush()
    except art_service.ArtValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    _audit(db, admin.id, "art_override_set", request)
    db.commit()
    db.refresh(row)
    return _serialize(row)


# ---------------------------------------------------------------------------
# Public (authenticated) read router: mounted under /api/art
# ---------------------------------------------------------------------------
read_router = APIRouter()


def optional_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Optional[User]:
    """Resolve the bearer user if a token is present, else None.

    A real dependency (not an inline call) so test dependency overrides on
    `current_user` still apply through it, and so a request with no
    Authorization header returns None instead of 401. The route decides
    whether None is acceptable (it is, only when a valid signature is present).
    A present-but-invalid bearer still 401s, exactly as before.
    """
    if not authorization:
        return None
    token = get_bearer_token(authorization)
    return current_user(token=token, db=db)


@read_router.get("/mixes")
def mix_art(
    _user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Optional[str]]:
    """`{mix key: art URL or null}` for the four home mixes. A URL (with the
    usual `?v=` cache key) means an admin set a picture; null means the web
    shows its static default from /mix/<key>.svg."""
    return art_service.mix_art_urls(db)


@read_router.get("/{entity_kind}/{entity_id}/{role}")
def serve_art(
    entity_kind: str,
    entity_id: uuid.UUID,
    role: str,
    user: Annotated[Optional[User], Depends(optional_current_user)],
    db: Annotated[Session, Depends(get_db)],
    uid: Optional[str] = None,
    exp: Optional[int] = None,
    sig: Optional[str] = None,
    sid: Optional[str] = None,
    w: Optional[int] = None,
    if_none_match: Annotated[Optional[str], Header()] = None,
) -> Response:
    """Stream the override's on-disk file. 404 if no override exists.

    Accepts either a bearer token (unchanged) or a short-lived HMAC-signed
    query (`uid`/`sid`/`exp`/`sig`, bound to this exact art path and the
    issuing session) so a header-less client (the Android media notification)
    can load the image.
    """
    if user is None:
        # No bearer. A valid signed query is the only other way in. A signature
        # that is present but bad or expired is a hard 401; it never falls
        # through to an unauthenticated read.
        if not (
            uid is not None and exp is not None and sig is not None and sid is not None
            and security_service.verify_art_url_params(
                entity_kind, entity_id, role, uid, sid, exp, sig,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="art_auth_required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # SEC-P1-2: signature good; the issuing session must still be live.
        if not session_authorizes(db, sid):
            raise HTTPException(status_code=403, detail="session_revoked")
    try:
        art_service.validate_kind_role(entity_kind, role)
        if entity_kind == "mix" and entity_id not in art_service.MIX_IDS.values():
            raise art_service.ArtValidationError("unknown mix", status_code=404)
    except art_service.ArtValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    path = art_service.local_file_path(
        db,
        entity_kind=entity_kind,
        entity_id=entity_id,
        role=role,
    )
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="art_not_found",
        )
    # `w=300` or `w=600` serves the smaller WebP copy (made on save, or on
    # demand here if missing); anything else serves the original.
    width = art_service.parse_width(w)
    served = path
    if width is not None:
        served = art_service.ensure_art_copy(path, width) or path
        if served == path:
            width = None
    # Cache aggressively. resolve_art appends ?v=<set_at_unix> to every art
    # URL (services/art.py resolve_art), so re-picking an image changes the
    # URL and busts the cache on its own. `immutable` tells the browser not
    # to revalidate for a matched URL, which kills the repeat-visit poster
    # storm entirely. Private, because art stays behind auth. The ETag is
    # derived from the served file's stat (mtime + size) plus the width, so
    # each size has its own tag and a conditional request can 304.
    st = os.stat(served)
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}' + (f"-w{width}" if width else "") + '"'
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": etag,
    }
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    # Media type is resolved from the extension so jpg/png/webp are all
    # served with the right Content-Type without us tracking it in the DB.
    return FileResponse(served, headers=headers)


def _etag_matches(header: Optional[str], etag: str) -> bool:
    """RFC 9110 weak comparison of an If-None-Match header against `etag`."""
    if not header:
        return False
    if header.strip() == "*":
        return True

    def norm(tag: str) -> str:
        tag = tag.strip()
        return tag[2:] if tag.startswith("W/") else tag

    return any(norm(t) == etag for t in header.split(","))
