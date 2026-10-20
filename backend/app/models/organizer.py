"""Organizer journal models: per-library rename/retag run history."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._mixins import UUIDPKMixin, utcnow


class OrganizerJournal(UUIDPKMixin, Base):
    __tablename__ = "organizer_journals"

    library_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("libraries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="preview",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    undo_applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    items: Mapped[list["OrganizerJournalItem"]] = relationship(
        back_populates="journal",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="OrganizerJournalItem.sort_order",
    )

    __table_args__ = (
        Index("ix_organizer_journals_library", "library_id"),
        Index("ix_organizer_journals_started_at", "started_at"),
    )


class OrganizerJournalItem(UUIDPKMixin, Base):
    __tablename__ = "organizer_journal_items"

    journal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizer_journals.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    old_path: Mapped[str] = mapped_column(Text, nullable=False)
    new_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    journal: Mapped["OrganizerJournal"] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_organizer_journal_items_journal", "journal_id"),
        Index("ix_organizer_journal_items_media_file", "media_file_id"),
    )
