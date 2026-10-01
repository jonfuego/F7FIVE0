"""Watch progress and history."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import UUIDPKMixin


class WatchProgress(Base):
    """Composite PK (user_id, media_file_id). Last-seen position per pair."""

    __tablename__ = "watch_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_watch_progress_user_updated", "user_id", "updated_at"),
    )


class WatchHistory(UUIDPKMixin, Base):
    """One row per playback session (start → end)."""

    __tablename__ = "watch_history"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_position_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_watch_history_user_started", "user_id", "started_at"),
    )


class PlaybackQueue(Base):
    """One row per user. Mirrors the client audio queue for cross-device
    handoff. `last_writer_id` is an opaque per-tab string the UI uses to
    suppress echo from its own writes when polling for changes."""

    __tablename__ = "playback_queues"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    current_index: Mapped[Optional[int]] = mapped_column(Integer)
    repeat_mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="off",
    )
    shuffle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_writer_id: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
