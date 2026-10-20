"""Background bulk-action framework.

One job at a time (module-level lock). Status is persisted in app_settings
under BULK_JOB_KEY so Admin > Scans can poll it.

Supported actions: refresh_metadata, lock, unlock, add_to_collection.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db import db_session
from app.models.app_setting import AppSetting
from app.services import metadata_locks
from app.services import collections as collections_service

log = logging.getLogger("f7five0.bulk_actions")

BULK_JOB_KEY = "bulk_job_status"

# Lockable fields per kind -- mirrors _LOCKABLE_FIELDS in admin_metadata_editor.py
# (kept here to avoid circular import; admin_metadata_editor imports from here).
LOCKABLE_FIELDS: dict[str, list[str]] = {
    "movie": ["title", "sort_title", "year", "overview", "genres", "tagline", "runtime_min"],
    "series": ["title", "sort_title", "overview", "first_aired"],
    "episode": ["title", "overview", "air_date"],
    "artist": ["name", "sort_name", "overview", "country", "formed_year", "disbanded_year"],
    "album": ["title", "sort_title", "release_date", "genres"],
    "track": ["title", "sort_title", "track_number", "disc_number", "credited_as"],
    "music_video": ["title", "sort_title", "year", "track_number", "disc_number"],
    "music_video_release": ["title", "release_year"],
}

_lock = threading.Lock()


def _read_status(db: Session) -> Optional[dict]:
    row = db.get(AppSetting, BULK_JOB_KEY)
    return row.value if row else None


def _write_status(db: Session, **fields) -> None:
    row = db.get(AppSetting, BULK_JOB_KEY)
    if row is None:
        row = AppSetting(key=BULK_JOB_KEY, value={})
        db.add(row)
    current = dict(row.value or {})
    current.update(fields)
    row.value = current
    db.commit()


def is_running(db: Session) -> bool:
    status = _read_status(db)
    return bool(status and status.get("state") == "running")


def run_bulk_action(
    action: str,
    kind: str,
    ids: list[uuid.UUID],
    params: Optional[dict] = None,
) -> None:
    """Run a bulk action. Called from a background scheduler job.
    Opens its own DB session per item for safety.
    """
    if not _lock.acquire(blocking=False):
        log.info("bulk action already running; skipping enqueued call")
        return
    try:
        params = params or {}
        total = len(ids)
        started = datetime.now(timezone.utc).isoformat()
        with db_session() as db:
            _write_status(
                db,
                state="running",
                action=action,
                kind=kind,
                total=total,
                done=0,
                errors=0,
                started_at=started,
                finished_at=None,
            )
        done = 0
        errors = 0
        for i, entity_id in enumerate(ids):
            try:
                with db_session() as db:
                    _apply_action(db, action, kind, entity_id, params)
                done += 1
            except Exception as exc:
                log.warning("bulk_action %s %s %s failed: %s", action, kind, entity_id, exc)
                errors += 1
            if (i + 1) % 25 == 0:
                with db_session() as db:
                    _write_status(db, done=done, errors=errors)
        finished = datetime.now(timezone.utc).isoformat()
        with db_session() as db:
            _write_status(
                db,
                state="done",
                done=done,
                errors=errors,
                finished_at=finished,
            )
    finally:
        _lock.release()


def _apply_action(
    db: Session, action: str, kind: str, entity_id: uuid.UUID, params: dict,
) -> None:
    if action == "refresh_metadata":
        _refresh_metadata(db, kind, entity_id)
    elif action == "lock":
        fields = LOCKABLE_FIELDS.get(kind, [])
        metadata_locks.set_locks(db, kind, entity_id, fields)
        db.commit()
    elif action == "unlock":
        fields = LOCKABLE_FIELDS.get(kind, [])
        metadata_locks.clear_locks(db, kind, entity_id, fields)
        db.commit()
    elif action == "add_to_collection":
        coll_id = params.get("collection_id")
        if not coll_id:
            raise ValueError("add_to_collection requires collection_id")
        if isinstance(coll_id, str):
            coll_id = uuid.UUID(coll_id)
        collections_service.add_items(db, coll_id, kind, [entity_id])
        db.commit()
    else:
        raise ValueError(f"unknown bulk action: {action}")


def _refresh_metadata(db: Session, kind: str, entity_id: uuid.UUID) -> None:
    """Force-enrich one entity, bypassing the TTL skip."""
    if kind == "movie":
        from app.services.metadata.runner import enrich_movie
        enrich_movie(db, entity_id, force=True)
    elif kind in ("artist",):
        from app.services.metadata.runner import enrich_artist
        enrich_artist(db, entity_id, force=True)
    elif kind in ("album",):
        from app.services.metadata.runner import enrich_album
        enrich_album(db, entity_id, force=True)
