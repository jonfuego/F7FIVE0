"""Detected intro/credits markers per media file (Skip Intro / Skip Credits)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import UUIDPKMixin


KIND_INTRO = "intro"
KIND_CREDITS = "credits"

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"


class MediaMarker(UUIDPKMixin, Base):
    """One detected (or manual) range on a media file.

    `kind` is intro or credits; the player shows a skip button while
    currentTime is inside [start_sec, end_sec) and seeks to end_sec on
    click. Unique on (media_file_id, kind) so re-analysis upserts. `source`
    is auto (ffmpeg heuristic) or manual (reserved for a future editor)."""

    __tablename__ = "media_markers"

    media_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    start_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    end_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=SOURCE_AUTO)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("media_file_id", "kind", name="uq_media_markers_file_kind"),
        Index("ix_media_markers_file", "media_file_id"),
    )
