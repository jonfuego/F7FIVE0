"""Per-field metadata editor locks.

One row locks one field on one entity, preventing the folder scan, *arr sync,
enrichment runners, backfills, and Fix Match from overwriting a value the admin
deliberately set. The lock is created automatically whenever an admin edits a
canonical field via PATCH /api/admin/metadata/{kind}/{entity_id}, and removed
explicitly via PATCH /api/admin/metadata/{kind}/{entity_id}/locks.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import UUIDPKMixin


class MetadataLock(UUIDPKMixin, Base):
    __tablename__ = "metadata_locks"

    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "entity_kind", "entity_id", "field_name",
            name="uq_metadata_locks_kind_entity_field",
        ),
        Index("ix_metadata_locks_entity", "entity_kind", "entity_id"),
    )
