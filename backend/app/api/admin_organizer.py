"""Admin organizer endpoints.

Router prefix: /api/admin/library/organizer

Endpoints:
  GET  /{library_id}/settings
  PUT  /{library_id}/settings
  GET  /{library_id}/template-preview
  POST /{library_id}/preview
  POST /{library_id}/apply/{journal_id}
  POST /{library_id}/undo/{journal_id}
  GET  /journals
  GET  /journals/{journal_id}
  GET  /{library_id}/recycle
  DELETE /{library_id}/recycle
  DELETE /versions/{media_file_id}

All admin-only.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.library import Library
from app.models.media_file import MediaFile
from app.models.organizer import OrganizerJournal, OrganizerJournalItem
from app.models.user import User
from app.services import library_settings, organizer
from app.services.flipflop_guard import check_flipflop

router = APIRouter(tags=["admin-organizer"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class OrganizerSettingsIn(BaseModel):
    ownership: Optional[str] = None
    naming_template: Optional[dict] = None
    tag_profile: Optional[dict] = None
    recycle_folder: Optional[str] = None


class OrganizerJournalItemOut(BaseModel):
    id: uuid.UUID
    item_kind: str
    old_path: str
    new_path: Optional[str] = None
    error: Optional[str] = None
    sort_order: int

    class Config:
        from_attributes = True


class OrganizerJournalOut(BaseModel):
    id: uuid.UUID
    library_id: Optional[uuid.UUID] = None
    state: str
    started_at: str
    finished_at: Optional[str] = None
    item_count: int
    error: Optional[str] = None
    undo_applied_at: Optional[str] = None
    items: list[OrganizerJournalItemOut] = []

    class Config:
        from_attributes = True


class TemplatePreviewItem(BaseModel):
    media_file_id: uuid.UUID
    old_path: str
    new_path: Optional[str] = None
    old_tags: Optional[dict] = None
    new_tags: Optional[dict] = None


class RecycleItem(BaseModel):
    path: str
    filename: str
    size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _journal_out(j: OrganizerJournal, include_items: bool = True) -> OrganizerJournalOut:
    items_out = []
    if include_items:
        for it in (j.items or []):
            items_out.append(OrganizerJournalItemOut(
                id=it.id,
                item_kind=it.item_kind,
                old_path=it.old_path,
                new_path=it.new_path,
                error=it.error,
                sort_order=it.sort_order,
            ))
    return OrganizerJournalOut(
        id=j.id,
        library_id=j.library_id,
        state=j.state,
        started_at=j.started_at.isoformat() if j.started_at else "",
        finished_at=j.finished_at.isoformat() if j.finished_at else None,
        item_count=j.item_count,
        error=j.error,
        undo_applied_at=j.undo_applied_at.isoformat() if j.undo_applied_at else None,
        items=items_out,
    )


def _get_lib_or_404(db: Session, library_id: uuid.UUID) -> Library:
    lib = db.get(Library, library_id)
    if lib is None:
        raise HTTPException(status_code=404, detail="library_not_found")
    return lib


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# GET /journals must come before GET /{library_id}/... so the static path wins.

@router.get("/journals")
def list_journals(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    library_id: Optional[uuid.UUID] = None,
    limit: int = 20,
) -> list[OrganizerJournalOut]:
    q = select(OrganizerJournal).order_by(OrganizerJournal.started_at.desc()).limit(limit)
    if library_id is not None:
        q = q.where(OrganizerJournal.library_id == library_id)
    journals = db.scalars(q).all()
    return [_journal_out(j, include_items=False) for j in journals]


@router.get("/journals/{journal_id}")
def get_journal(
    journal_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> OrganizerJournalOut:
    j = db.get(OrganizerJournal, journal_id)
    if j is None:
        raise HTTPException(status_code=404, detail="journal_not_found")
    return _journal_out(j, include_items=True)


@router.delete("/versions/{media_file_id}", status_code=200)
def delete_version(
    media_file_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Move a file to the recycle folder and remove its media_file row.

    Returns {recycle_path, item_deleted}.
    """
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise HTTPException(status_code=404, detail="media_file_not_found")
    library_id = mf.library_id
    if library_id is None:
        raise HTTPException(status_code=422, detail="media_file_has_no_library")
    try:
        recycle_path, item_deleted = organizer.move_to_recycle(db, media_file_id, library_id)
        db.commit()
        return {"recycle_path": recycle_path, "item_deleted": item_deleted}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{library_id}/settings")
def get_settings(
    library_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    lib = _get_lib_or_404(db, library_id)
    s = library_settings.get_settings(db, library_id)
    s.setdefault("ownership", library_settings.get_ownership(db, library_id))
    s.setdefault("recycle_folder", organizer.RECYCLE_DIR)
    from app.services.naming_templates import PRESET_PLEX, PRESET_ARR, PRESET_FLAT
    s["presets"] = {"plex": PRESET_PLEX, "arr": PRESET_ARR, "flat": PRESET_FLAT}
    s["flip_flop_warnings"] = check_flipflop(lib.kind.value)
    return s


@router.put("/{library_id}/settings", status_code=200)
def save_settings(
    library_id: uuid.UUID,
    body: OrganizerSettingsIn,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    lib = _get_lib_or_404(db, library_id)
    s = library_settings.get_settings(db, library_id)
    if body.ownership is not None:
        s["ownership"] = body.ownership
    if body.naming_template is not None:
        s["naming_template"] = body.naming_template
    if body.tag_profile is not None:
        s["tag_profile"] = body.tag_profile
    if body.recycle_folder is not None:
        s["recycle_folder"] = body.recycle_folder
    library_settings.save_settings(db, library_id, s)
    db.commit()
    warnings = check_flipflop(lib.kind.value)
    return {"flip_flop_warnings": warnings}


@router.get("/{library_id}/template-preview")
def template_preview(
    library_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 10,
) -> list[TemplatePreviewItem]:
    """Return up to `limit` real items showing old_path, new_path, old_tags, new_tags
    under the current template and tag profile. No disk writes."""
    from app.models.media_file import MediaFile as MF, MediaKind, ScanState
    import json
    from app.services import tag_writer
    from app.services.path_map import translate as translate_path

    _get_lib_or_404(db, library_id)
    settings = library_settings.get_settings(db, library_id)
    naming_tpl = settings.get("naming_template") or {}
    tag_profile = settings.get("tag_profile") or {}

    folder_paths = organizer._get_library_folders(db, library_id)

    media_files = db.scalars(
        select(MF).where(
            MF.library_id == library_id,
            MF.scan_state == ScanState.ready,
        ).limit(limit * 5)  # over-fetch so we can filter down to limit meaningful ones
    ).all()

    results: list[TemplatePreviewItem] = []
    for mf in media_files:
        if len(results) >= limit:
            break
        tokens = organizer._build_tokens(db, mf)
        if tokens is None:
            continue
        translated_path = translate_path(mf.path, db) or mf.path
        containing_folder = organizer._folder_for_file(translated_path, folder_paths)
        if not containing_folder:
            continue

        kind_key = organizer._kind_key(mf)
        template = naming_tpl.get(kind_key)

        new_path = None
        if template:
            new_path = organizer._compute_new_path(mf, tokens, template, containing_folder)

        old_tags = None
        new_tags = None
        if tag_profile and mf.kind == MediaKind.track:
            old_tags = tag_writer.backup_tags(translated_path)
            new_tags = organizer._compute_new_tags(mf, tokens, db)

        results.append(TemplatePreviewItem(
            media_file_id=mf.id,
            old_path=mf.path,
            new_path=new_path,
            old_tags=old_tags,
            new_tags=new_tags,
        ))

    return results


@router.post("/{library_id}/preview", status_code=202)
def trigger_preview(
    library_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Trigger an organizer preview run in the background.

    Returns 409 when a scan or organizer run is already active.
    """
    from app.services import scan_status as ss

    _get_lib_or_404(db, library_id)

    if ss.is_running(db):
        raise HTTPException(status_code=409, detail="scan_running")
    if ss.arr_is_running(db):
        raise HTTPException(status_code=409, detail="arr_sync_running")
    if organizer.is_organizer_running():
        raise HTTPException(status_code=409, detail="organizer_running")

    from app import scheduler as sch
    sch.trigger_organizer_preview(library_id, _admin.id)
    return {"status": "queued"}


@router.post("/{library_id}/apply/{journal_id}", status_code=202)
def apply_journal(
    library_id: uuid.UUID,
    journal_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Start a background apply job for a preview journal.

    Returns 409 when the journal is not in "preview" state or the organizer is running.
    """
    _get_lib_or_404(db, library_id)

    j = db.get(OrganizerJournal, journal_id)
    if j is None:
        raise HTTPException(status_code=404, detail="journal_not_found")
    if j.state != "preview":
        raise HTTPException(status_code=409, detail=f"journal_not_preview")

    from app.services import scan_status as ss
    if ss.is_running(db):
        raise HTTPException(status_code=409, detail="scan_running")
    if ss.arr_is_running(db):
        raise HTTPException(status_code=409, detail="arr_sync_running")
    if organizer.is_organizer_running():
        raise HTTPException(status_code=409, detail="organizer_already_running")

    from app import scheduler as sch
    sch.trigger_organizer_apply(journal_id, _admin.id)
    return {"status": "queued"}


@router.post("/{library_id}/undo/{journal_id}", status_code=202)
def undo_journal(
    library_id: uuid.UUID,
    journal_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Start a background undo job for a completed journal.

    Returns 409 when the journal is not in "done" state or the organizer is running.
    """
    _get_lib_or_404(db, library_id)

    j = db.get(OrganizerJournal, journal_id)
    if j is None:
        raise HTTPException(status_code=404, detail="journal_not_found")
    if j.state != "done":
        raise HTTPException(status_code=409, detail=f"journal_state_{j.state}")

    from app.services import scan_status as ss
    if ss.is_running(db):
        raise HTTPException(status_code=409, detail="scan_running")
    if ss.arr_is_running(db):
        raise HTTPException(status_code=409, detail="arr_sync_running")
    if organizer.is_organizer_running():
        raise HTTPException(status_code=409, detail="organizer_already_running")

    from app import scheduler as sch
    sch.trigger_organizer_undo(journal_id, _admin.id)
    return {"status": "queued"}


@router.get("/{library_id}/recycle")
def list_recycle(
    library_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RecycleItem]:
    _get_lib_or_404(db, library_id)
    s = library_settings.get_settings(db, library_id)
    recycle_name = s.get("recycle_folder", organizer.RECYCLE_DIR)
    folder_paths = organizer._get_library_folders(db, library_id)
    items = organizer.list_recycle(library_id, folder_paths, recycle_name)
    return [RecycleItem(**item) for item in items]


@router.delete("/{library_id}/recycle", status_code=200)
def empty_recycle_endpoint(
    library_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _get_lib_or_404(db, library_id)
    s = library_settings.get_settings(db, library_id)
    recycle_name = s.get("recycle_folder", organizer.RECYCLE_DIR)
    folder_paths = organizer._get_library_folders(db, library_id)
    count = organizer.empty_recycle(folder_paths, recycle_name)
    return {"deleted": count}
