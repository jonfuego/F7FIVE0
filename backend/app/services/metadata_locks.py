"""Metadata editor field locks.

A lock prevents any writer (folder scan, *arr sync, enrichment runner,
backfill, Fix Match) from overwriting a canonical field the admin has
explicitly set via the metadata editor.

The lock table uses a unique constraint on (entity_kind, entity_id, field_name)
so upserts are safe and there is at most one lock row per field per entity.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.metadata_lock import MetadataLock

if TYPE_CHECKING:
    pass


def is_locked(db: Session, entity_kind: str, entity_id: uuid.UUID, field_name: str) -> bool:
    """Return True when a lock row exists for this (entity_kind, entity_id, field_name)."""
    return bool(
        db.scalar(
            select(MetadataLock.id).where(
                MetadataLock.entity_kind == entity_kind,
                MetadataLock.entity_id == entity_id,
                MetadataLock.field_name == field_name,
            ).limit(1)
        )
    )


def locked_fields(db: Session, entity_kind: str, entity_id: uuid.UUID) -> set[str]:
    """All locked field names for one entity."""
    rows = db.scalars(
        select(MetadataLock.field_name).where(
            MetadataLock.entity_kind == entity_kind,
            MetadataLock.entity_id == entity_id,
        )
    ).all()
    return set(rows)


def bulk_locked_fields(
    db: Session,
    entity_kind: str,
    entity_ids: list[uuid.UUID],
) -> dict[uuid.UUID, set[str]]:
    """Locked field names per entity for a batch of entity ids.

    One query fetches all lock rows for the entire batch, so per-item scan
    and sync loops can call this once rather than once per item.
    """
    if not entity_ids:
        return {}
    rows = db.execute(
        select(MetadataLock.entity_id, MetadataLock.field_name).where(
            MetadataLock.entity_kind == entity_kind,
            MetadataLock.entity_id.in_(entity_ids),
        )
    ).all()
    result: dict[uuid.UUID, set[str]] = {eid: set() for eid in entity_ids}
    for eid, fname in rows:
        if eid in result:
            result[eid].add(fname)
    return result


def set_locks(
    db: Session,
    entity_kind: str,
    entity_id: uuid.UUID,
    fields: list[str],
) -> None:
    """Create lock rows for each field in `fields` (idempotent: skips existing)."""
    now = datetime.now(timezone.utc)
    for field_name in fields:
        exists = db.scalar(
            select(MetadataLock.id).where(
                MetadataLock.entity_kind == entity_kind,
                MetadataLock.entity_id == entity_id,
                MetadataLock.field_name == field_name,
            ).limit(1)
        )
        if exists is None:
            db.add(MetadataLock(
                id=uuid.uuid4(),
                entity_kind=entity_kind,
                entity_id=entity_id,
                field_name=field_name,
                locked_at=now,
            ))
    db.flush()


def clear_locks(
    db: Session,
    entity_kind: str,
    entity_id: uuid.UUID,
    fields: list[str],
) -> None:
    """Remove lock rows for each field in `fields`."""
    if not fields:
        return
    db.execute(
        delete(MetadataLock).where(
            MetadataLock.entity_kind == entity_kind,
            MetadataLock.entity_id == entity_id,
            MetadataLock.field_name.in_(fields),
        )
    )
    db.flush()
