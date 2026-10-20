"""Admin metadata editor: canonical field editing with per-field locks.

Endpoints:
  GET  /api/admin/metadata/{kind}/{entity_id}
      Returns current canonical field values, locked_fields set, and any
      display overrides that conflict with the canonical value.
  PATCH /api/admin/metadata/{kind}/{entity_id}
      Writes one or more canonical fields to the item row and auto-locks
      every written field.
  PATCH /api/admin/metadata/{kind}/{entity_id}/locks
      Explicitly lock or unlock fields without touching the row values.

All endpoints are admin-only.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.media_file import MediaKind
from app.models.movie import Movie
from app.models.music import Album, Artist, MusicVideo, MusicVideoRelease, Track
from app.models.tv import Episode, Series
from app.models.user import User
from app.services import metadata_locks

router = APIRouter(prefix="/metadata", tags=["admin-metadata-editor"])


# ---------------------------------------------------------------------------
# Kind → ORM class and lockable fields
# ---------------------------------------------------------------------------
_EDITOR_KIND_MAP: dict[str, Any] = {
    "movie": Movie,
    "series": Series,
    "episode": Episode,
    "artist": Artist,
    "album": Album,
    "track": Track,
    "music_video": MusicVideo,
    "music_video_release": MusicVideoRelease,
}

_LOCKABLE_FIELDS: dict[str, set[str]] = {
    "movie": {"title", "sort_title", "year", "overview", "genres", "tagline", "runtime_min"},
    "series": {"title", "sort_title", "overview", "first_aired"},
    "episode": {"title", "overview", "air_date"},
    "artist": {"name", "sort_name", "overview", "country", "formed_year", "disbanded_year"},
    "album": {"title", "sort_title", "release_date", "genres"},
    "track": {"title", "sort_title", "track_number", "disc_number", "credited_as"},
    "music_video": {"title", "sort_title", "year", "track_number", "disc_number"},
    "music_video_release": {"title", "release_year"},
}


def _get_entity(db: Session, kind: str, entity_id: uuid.UUID):
    model_cls = _EDITOR_KIND_MAP.get(kind)
    if model_cls is None:
        raise HTTPException(status_code=422, detail="invalid_kind")
    row = db.get(model_cls, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind}_not_found")
    return row


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class MetadataFieldsOut(BaseModel):
    kind: str
    entity_id: uuid.UUID
    fields: dict[str, Any]
    locked_fields: list[str]
    overridden_fields: dict[str, Any]

    model_config = {"from_attributes": True}


class MetadataPatch(BaseModel):
    title: Optional[str] = None
    sort_title: Optional[str] = None
    year: Optional[int] = None
    overview: Optional[str] = None
    genres: Optional[list] = None
    tagline: Optional[str] = None
    runtime_min: Optional[int] = None
    first_aired: Optional[date] = None
    air_date: Optional[date] = None
    name: Optional[str] = None
    sort_name: Optional[str] = None
    country: Optional[str] = None
    formed_year: Optional[int] = None
    disbanded_year: Optional[int] = None
    release_date: Optional[date] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    credited_as: Optional[str] = None
    release_year: Optional[int] = None
    adopt_overrides: Optional[list[str]] = None

    model_config = {"extra": "ignore"}


class LocksUpdate(BaseModel):
    lock: Optional[list[str]] = None
    unlock: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_fields(kind: str, row) -> dict[str, Any]:
    """Read all lockable fields from an ORM row as a dict."""
    lockable = _LOCKABLE_FIELDS.get(kind, set())
    out: dict[str, Any] = {}
    for field in sorted(lockable):
        val = getattr(row, field, None)
        if isinstance(val, date) and not isinstance(val, type(None)):
            val = val.isoformat()
        out[field] = val
    return out


def _overridden_fields(kind: str, row) -> dict[str, Any]:
    """Lockable fields that have a conflicting value in row.overrides."""
    overrides: dict = getattr(row, "overrides", {}) or {}
    lockable = _LOCKABLE_FIELDS.get(kind, set())
    out: dict[str, Any] = {}
    for key, val in overrides.items():
        if key in lockable and val is not None:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/{kind}/{entity_id}", response_model=MetadataFieldsOut)
def get_metadata(
    kind: str,
    entity_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MetadataFieldsOut:
    """Return current canonical field values and the locked-field set."""
    row = _get_entity(db, kind, entity_id)
    return MetadataFieldsOut(
        kind=kind,
        entity_id=entity_id,
        fields=_read_fields(kind, row),
        locked_fields=sorted(metadata_locks.locked_fields(db, kind, entity_id)),
        overridden_fields=_overridden_fields(kind, row),
    )


@router.patch("/{kind}/{entity_id}", response_model=MetadataFieldsOut)
def patch_metadata(
    kind: str,
    entity_id: uuid.UUID,
    body: MetadataPatch,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MetadataFieldsOut:
    """Write canonical fields and auto-lock every written field.

    Omitted fields are untouched. A null value clears a nullable column.
    ``adopt_overrides`` copies the listed override keys to their canonical
    columns (locked), then removes those keys from ``overrides``.
    """
    row = _get_entity(db, kind, entity_id)
    lockable = _LOCKABLE_FIELDS.get(kind, set())

    written: list[str] = []
    raw = body.model_dump(exclude_none=False, exclude_unset=True, exclude={"adopt_overrides"})
    for field, value in raw.items():
        if field not in lockable:
            continue
        setattr(row, field, value)
        written.append(field)

    # adopt_overrides: move override values to canonical columns.
    adopt = body.adopt_overrides or []
    overrides: dict = getattr(row, "overrides", {}) or {}
    for field in adopt:
        if field not in lockable:
            continue
        if field in overrides:
            setattr(row, field, overrides[field])
            overrides = {k: v for k, v in overrides.items() if k != field}
            written.append(field)
    if adopt:
        row.overrides = overrides

    if written:
        metadata_locks.set_locks(db, kind, entity_id, written)

    db.commit()
    db.refresh(row)
    return MetadataFieldsOut(
        kind=kind,
        entity_id=entity_id,
        fields=_read_fields(kind, row),
        locked_fields=sorted(metadata_locks.locked_fields(db, kind, entity_id)),
        overridden_fields=_overridden_fields(kind, row),
    )


@router.patch("/{kind}/{entity_id}/locks", response_model=MetadataFieldsOut)
def update_locks(
    kind: str,
    entity_id: uuid.UUID,
    body: LocksUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MetadataFieldsOut:
    """Explicitly lock or unlock fields without touching row values."""
    row = _get_entity(db, kind, entity_id)
    lockable = _LOCKABLE_FIELDS.get(kind, set())

    to_lock = [f for f in (body.lock or []) if f in lockable]
    to_unlock = [f for f in (body.unlock or []) if f in lockable]

    if to_lock:
        metadata_locks.set_locks(db, kind, entity_id, to_lock)
    if to_unlock:
        metadata_locks.clear_locks(db, kind, entity_id, to_unlock)

    db.commit()
    return MetadataFieldsOut(
        kind=kind,
        entity_id=entity_id,
        fields=_read_fields(kind, row),
        locked_fields=sorted(metadata_locks.locked_fields(db, kind, entity_id)),
        overridden_fields=_overridden_fields(kind, row),
    )
